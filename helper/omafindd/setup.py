import asyncio
import json
import logging
import os
import signal
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

from . import bindings, discovery, errors
from .install import RuntimeJob


def mounted_volumes():
    from .store import mounted_volumes as resolve
    return resolve()

HOME = Path.home()
KINDS = ("text", "pdf", "image", "video", "audio")


class SetupService:
    TYPES = {
        "runtime_status",
        "runtime_install",
        "runtime_pause",
        "discover_start",
        "discover_stop",
        "discover_children",
        "fs_list",
        "binds_get",
        "index_start",
        "index_progress",
        "drive_decision",
    }
    # A finished walk answers repeat visits for this long; after it the next visit walks again.
    WALK_TTL = 300.0

    def __init__(
        self,
        *,
        data_dir: Path,
        plugin_root: Path,
        settings,
        broadcast,
        runtime: RuntimeJob,
        top=discovery.top,
        walk=discovery.Walk,
        children=discovery.children,
        estimate_device=discovery.device,
        volume_of=discovery._volume_of,
        list_dirs=discovery.list_dirs,
        spawn=asyncio.create_subprocess_exec,
        run=subprocess.run,
        clock=time.monotonic,
        home=HOME,
        model_ready=lambda: True,
        paused=lambda: False,
        check_disk=None,
        push_status=None,
    ):
        self.data_dir, self.plugin_root, self.home = data_dir, plugin_root, home
        self.settings, self.broadcast, self.runtime = settings, broadcast, runtime
        self.top, self.walk, self.children = top, walk, children
        self.estimate_device, self.volume_of, self.list_dirs = estimate_device, volume_of, list_dirs
        self.spawn, self.clock = spawn, clock
        self.run = run
        self.model_ready, self.paused = model_ready, paused
        self.check_disk, self.push_status = check_disk, push_status
        self.ignored = set()
        self._deferred = set()
        self._active_volume = None
        self._walks = {}
        self._roots = {}
        self._walked = {}
        self._discovery = set()
        self._walk_tasks = {}
        self._clients = {}
        self._client_tokens = {}
        self._walk_lock = asyncio.Lock()
        self._index = None
        self._starting = None
        self._index_lock = asyncio.Lock()
        self._last = None
        self._last_at = float("-inf")
        self._final = True
        self._mounts = {}

    async def handle(self, message: dict, *, client=None) -> dict:
        kind = message["t"]
        try:
            if kind in ("runtime_status", "runtime_install", "runtime_pause"):
                method = {
                    "runtime_status": self.runtime.status,
                    "runtime_install": self.runtime.start,
                    "runtime_pause": self.runtime.pause,
                }[kind]
                return await method()
            if kind == "index_progress":
                return await asyncio.to_thread(self._progress)
            if kind == "discover_stop":
                await self.disconnect(client)
                return {"t": kind}
            if kind == "binds_get":
                return await asyncio.to_thread(self._binds)
            if kind == "discover_start":
                token = self._client_tokens.setdefault(client, object())
                volume = message.get("volume")
                if volume is not None and (not isinstance(volume, str) or not volume):
                    return errors.reply(kind, errors.bad_request("Invalid discovery volume"))
                body = await asyncio.to_thread(self.top, home=self.home, volume=volume)
                device = await asyncio.to_thread(self.estimate_device, self.home)
                if self._client_tokens.get(client) is not token:
                    return {"t": "discover_stop"}
                replay = []
                for root in body["roots"]:
                    self._roots[root["path"]] = root.get("volume")
                    walk, fresh = self._start_walk(root["path"])
                    self._clients.setdefault(client, set()).add(root["path"])
                    if not fresh:
                        replay.append(walk)
                if replay:
                    self._track(self._replay(replay))
                return {"t": "discover_result", "volume": volume, "home": str(self.home),
                        "device": device, "rates": discovery.RATES, **body}
            if kind == "discover_children":
                token = self._client_tokens.setdefault(client, object())
                path = message.get("path")
                if not isinstance(path, str) or not Path(path).is_absolute():
                    return errors.reply(kind, errors.bad_request("Pick an absolute folder path"))
                path = os.path.normpath(path)
                roots = [root for root in self._roots
                         if path == root or path.startswith(root.rstrip("/") + "/")]
                if path == "/" or (not roots and any(
                    path == root or path.startswith(root + "/")
                    for root in ("/proc", "/sys", "/dev", "/run")
                )):
                    failure = errors.bad_request("Pick a folder outside system paths")
                    return errors.reply(kind, failure)
                root = max(roots, key=len) if roots else path
                if not roots:
                    try:
                        volume = (await asyncio.to_thread(self.volume_of, Path(path)))[0]
                    except (OSError, ValueError, subprocess.SubprocessError):
                        volume = None
                    if self._client_tokens.get(client) is not token:
                        return {"t": "discover_stop"}
                    self._roots[root] = volume
                # An expired walk still answers; only discover_start walks a root again.
                walk = self._walks.get(root) or self._start_walk(root)[0]
                self._clients.setdefault(client, set()).add(root)
                body = await asyncio.to_thread(self.children, path, walk)
                volume = self._roots[root]
                if self._client_tokens.get(client) is not token:
                    return {"t": "discover_stop"}
                return {"t": kind, **body, "volume": volume}
            if kind == "fs_list":
                path = message.get("path")
                if (
                    not isinstance(path, str)
                    or not path
                    or not (Path(path).is_absolute() or path == "~" or path.startswith("~/"))
                ):
                    return errors.reply(kind, errors.bad_request("Pick an absolute folder path"))
                body = await asyncio.to_thread(self.list_dirs, path, home=self.home)
                return {"t": kind, **body}
            if kind == "drive_decision":
                uuid, choice = message.get("uuid"), message.get("choice")
                if not isinstance(uuid, str) or not uuid or choice not in ("scan", "ignore"):
                    return errors.reply(kind, errors.bad_request("Invalid drive decision"))
                if choice == "ignore":
                    self.ignored.add(uuid)
                return {"t": kind, "uuid": uuid, "choice": choice}
            if kind == "index_start":
                volume = message.get("volume")
                if volume is not None and (not isinstance(volume, str) or not volume):
                    return errors.reply(kind, errors.bad_request("Invalid indexing volume"))
                if self._starting is None or self._starting.done():
                    self._starting = asyncio.create_task(self._start_index(volume))
                return await asyncio.shield(self._starting)
            return errors.reply(kind, errors.bad_request("Unknown setup request"))
        except errors.UserFailure as failure:
            return errors.reply(kind, failure.error)
        except Exception as error:
            return errors.reply(kind, errors.internal(str(error) or type(error).__name__))

    def _binds(self):
        try:
            result = self.run(["hyprctl", "binds", "-j"], capture_output=True, text=True, timeout=5)
            if result.returncode:
                raise OSError(result.stderr.strip() or f"hyprctl exited with {result.returncode}")
            if not result.stdout.lstrip().startswith("["):
                raise ValueError("hyprctl did not return a JSON array")
            items = bindings.binds_items(bindings.parse_binds(result.stdout))
            return {"t": "binds", "binds": items}
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as error:
            reason = (f"{error.filename}: {error.strerror}"
                      if isinstance(error, OSError) and error.filename and error.strerror
                      else str(error) or type(error).__name__)
            raise errors.UserFailure(errors.binds_failed(reason)) from error

    def _track(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._discovery.add(task)
        task.add_done_callback(self._discovery.discard)
        return task

    def _start_walk(self, root):
        """The walk of `root`: the running or recent one, else a new one. Returns (walk, fresh)."""
        walk = self._walks.get(root)
        finished = self._walked.get(root)
        if walk is not None and not getattr(walk, "error", None) and (
            finished is None or self.clock() - finished < self.WALK_TTL
        ):
            return walk, False
        walk = self.walk(Path(root))
        self._walks[root] = walk
        self._walked.pop(root, None)
        self._walk_tasks[root] = self._track(self._run_walk(root, walk))
        return walk, True

    async def _run_walk(self, root, walk):
        async with self._walk_lock:
            await self._count_walk(root, walk)

    async def _count_walk(self, root, walk):
        if self._walks.get(root) is not walk:
            return
        loop = asyncio.get_running_loop()
        batches = asyncio.Queue()
        worker = None

        def emit(batch):
            loop.call_soon_threadsafe(batches.put_nowait, batch)

        def run():
            try:
                walk.run(emit)
            except Exception as error:
                walk.done = True
                walk.error = errors.scan_failed(root, str(error) or type(error).__name__).to_dict()
                emit({"root": root, "counts": {}, "done": True, "seconds": None,
                      "error": walk.error})

        try:
            await self.broadcast({"t": "discover_counts", "root": root, "counts": {},
                                  "done": False, "seconds": None, "reset": True})
            if self._walks.get(root) is not walk:
                return
            worker = asyncio.ensure_future(asyncio.to_thread(run))
            while True:
                batch = await batches.get()
                if self._walks.get(root) is walk:
                    await self.broadcast({"t": "discover_counts", **batch})
                if batch["done"]:
                    break
        except Exception as error:
            walk.stop()
            if worker is not None:
                await asyncio.gather(worker, return_exceptions=True)
            walk.done = True
            walk.error = errors.scan_failed(root, str(error) or type(error).__name__).to_dict()
            try:
                await self.broadcast({"t": "discover_counts", "root": root, "counts": {},
                                      "done": True, "seconds": None, "error": walk.error})
            except Exception:
                logging.exception("Could not broadcast discovery failure")
        finally:
            if worker is not None:
                await asyncio.gather(worker, return_exceptions=True)
            if self._walks.get(root) is walk and not getattr(walk, "error", None):
                self._walked[root] = self.clock()

    async def disconnect(self, client):
        self._client_tokens.pop(client, None)
        roots = self._clients.pop(client, set())
        tasks = []
        for root in roots:
            if any(root in interest for interest in self._clients.values()):
                continue
            walk = self._walks.get(root)
            if walk is None:
                continue
            walk.stop()
            if not walk.done:
                self._walks.pop(root, None)
                self._walked.pop(root, None)
            task = self._walk_tasks.get(root)
            if task is not None:
                tasks.append(task)
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _replay(self, walks):
        for walk in walks:
            if self._walks.get(str(walk.root)) is not walk:
                continue
            await self.broadcast({"t": "discover_counts", **walk.snapshot()})

    @property
    def busy(self):
        return ((self._starting is not None and not self._starting.done())
                or (self._index is not None and self._index.returncode is None))

    async def kick(self, volume=None):
        if self.check_disk is not None:
            await self.check_disk()
        if self.paused() or not self.model_ready():
            return
        if self.busy:
            self._deferred.add(volume)
            return
        self._starting = asyncio.create_task(self._start_index(volume))
        await asyncio.shield(self._starting)

    async def _start_index(self, volume=None):
        async with self._index_lock:
            settings = self.settings()
            if not settings.roots and not settings.code_roots:
                return errors.reply("index_start", errors.no_roots())
            if self.check_disk is not None:
                await self.check_disk()
            if self.paused() or not self.model_ready():
                return await asyncio.to_thread(self._progress)
            if self._index is not None and self._index.returncode is None:
                if volume != self._active_volume:
                    self._deferred.add(volume)
            else:
                self._active_volume = volume
                directory = self.data_dir / "index"
                directory.mkdir(parents=True, mode=0o700, exist_ok=True)
                log = directory / "reindex.log"
                descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(descriptor, "wb") as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    self._index = await self.spawn(
                        sys.executable,
                        str(self.plugin_root / "bin/omafind"),
                        "reindex",
                        "--incremental",
                        *(["--volume", volume] if volume is not None else []),
                        start_new_session=True,
                        stdout=stream,
                        stderr=stream,
                    )
                self._final = False
                self._last = None
                self._last_at = float("-inf")
            return await asyncio.to_thread(self._progress)

    def _device(self):
        if self._index is None or self._index.returncode is not None:
            return None, None
        try:
            queue, seen = [self._index.pid], set()
            while queue:
                pid = queue.pop()
                if pid in seen:
                    continue
                seen.add(pid)
                for task in Path(f"/proc/{pid}/task").glob("*/children"):
                    try:
                        queue.extend(int(p) for p in task.read_text().split())
                    except OSError:
                        continue
                try:
                    command = Path(f"/proc/{pid}/cmdline").read_bytes().decode()
                    args = command.strip("\0").split("\0")
                except OSError:
                    continue
                if not args or Path(args[0]).name != "llama-server":
                    continue
                cpu = any(
                    arg in ("-ngl", "--gpu-layers", "--n-gpu-layers")
                    and index + 1 < len(args)
                    and args[index + 1] == "0"
                    for index, arg in enumerate(args)
                )
                vram = None
                try:
                    result = subprocess.run(
                        [
                            "nvidia-smi",
                            "--query-compute-apps=pid,used_memory",
                            "--format=csv,noheader,nounits",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=2,
                    )
                    if result.returncode == 0:
                        for line in result.stdout.splitlines():
                            app, memory = line.split(",", 1)
                            if int(app) == pid:
                                vram = round(float(memory) / 1024, 1)
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
                return "cpu" if cpu else "gpu", vram
        except (OSError, ValueError):
            pass
        return None, None

    def _progress(self):
        kinds = {kind: {"done": 0, "total": 0} for kind in KINDS}
        kinds["pdf"]["pages"] = kinds["image"]["ocr"] = 0
        failed, problems, volumes = {}, [], {}
        volume = pending_volume = None
        try:
            self._mounts = mounted_volumes()
        except (OSError, subprocess.SubprocessError):
            pass
        ready = "NOT (state='pending' OR (state='partial' AND detail IS NULL))"
        for path in sorted((self.data_dir / "index").glob("*.sqlite")):
            if path.name == "code.sqlite":
                continue
            try:
                with closing(
                    sqlite3.connect(path.absolute().as_uri() + "?mode=rw", uri=True, timeout=0.05)
                ) as db:
                    meta = dict(db.execute("SELECT key,value FROM meta"))
                    current = meta.get("volume_uuid", path.stem)
                    volume = current
                    total, done = db.execute(
                        f"SELECT count(*),coalesce(sum({ready}),0) FROM files"
                    ).fetchone()
                    volumes[current] = {"label": meta.get("volume_label", "root"),
                                        "done": done, "total": total}
                    for kind, total, done in db.execute(
                        f"SELECT kind,count(*),sum({ready}) FROM files GROUP BY kind"
                    ):
                        if kind not in kinds:
                            continue
                        kinds[kind]["total"] += total
                        kinds[kind]["done"] += done or 0
                        if total != done:
                            pending_volume = current
                    kinds["pdf"]["pages"] += db.execute(
                        "SELECT coalesce(sum(json_extract(info,'$.pages')),0) FROM files "
                        f"WHERE kind='pdf' AND {ready}"
                    ).fetchone()[0]
                    kinds["image"]["ocr"] += db.execute(
                        "SELECT count(*) FROM files f WHERE kind='image' AND "
                        + ready
                        + " AND EXISTS (SELECT 1 FROM segments s JOIN fts ON fts.rowid=s.id "
                        "WHERE s.file=f.id AND s.kind='ocr' AND length(fts.body)>0)"
                    ).fetchone()[0]
                    for detail, count in db.execute(
                        "SELECT detail,count(*) FROM files WHERE state='failed' GROUP BY detail"
                    ):
                        reason = detail or "unknown"
                        failed[reason] = failed.get(reason, 0) + count
                    mount = self._mounts.get(current)
                    if mount is not None:
                        for rel, detail in db.execute(
                            "SELECT path,detail FROM files WHERE state='failed' "
                            "ORDER BY path LIMIT ?",
                            (50 - len(problems),),
                        ):
                            problems.append(
                                {"path": str(mount / rel), "reason": detail or "unknown"}
                            )
            except sqlite3.Error:
                continue
        skipped = {}
        try:
            run = json.loads((self.data_dir / "index/run.json").read_text())
            if self._index is None or run.get("pid") == self._index.pid:
                skipped = {
                    k: n for k, n in run.get("skipped", {}).items() if type(n) is int and n > 0
                }
        except (OSError, ValueError, AttributeError):
            pass
        done = sum(kind["done"] for kind in kinds.values())
        total = sum(kind["total"] for kind in kinds.values())
        device, vram = self._device()
        exit_code = self._index.returncode if self._index is not None else None
        return {
            "t": "progress",
            "running": self._index is not None and exit_code is None,
            **({"exit": exit_code} if exit_code not in (None, 0) else {}),
            "done": done,
            "queued": total - done,
            "volume": pending_volume or volume,
            "volumes": volumes,
            "device": device,
            "vram_gb": vram,
            "kinds": kinds,
            "skipped": skipped,
            "failed": failed,
            "problems": problems,
        }

    async def poll(self, *, now=None) -> None:
        if self._index is None or self._final:
            return
        body = await asyncio.to_thread(self._progress)
        now = self.clock() if now is None else now
        if not body["running"] or (body != self._last and now - self._last_at >= 0.5):
            await self.broadcast(body)
            if self.push_status is not None:
                await self.push_status(force=not body["running"])
            self._last, self._last_at = body, now
            if not body["running"]:
                self._final = True
                if "exit" in body:
                    log = self.data_dir / "index/reindex.log"
                    await self.broadcast(
                        errors.reply("index_start", errors.index_exited(body["exit"], log))
                    )

                if self._deferred:
                    volume = None if None in self._deferred else sorted(self._deferred)[0]
                    if volume is None:
                        self._deferred.clear()
                    else:
                        self._deferred.remove(volume)
                    await self.kick(volume)

    async def stop(self) -> None:
        self._client_tokens.clear()
        self._clients.clear()
        for walk in self._walks.values():
            walk.stop()
        await asyncio.gather(*self._discovery, return_exceptions=True)
        if self._starting is not None:
            await asyncio.gather(self._starting, return_exceptions=True)
        if self._index is not None and self._index.returncode is None:
            try:
                os.killpg(self._index.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self._index.wait(), 5)
            except TimeoutError:
                try:
                    os.killpg(self._index.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await self._index.wait()
        await self.runtime.stop()
