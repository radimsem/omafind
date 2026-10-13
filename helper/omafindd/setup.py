import asyncio
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

from . import discovery
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
        "discover_tree",
        "fs_list",
        "index_start",
        "drive_decision",
    }

    def __init__(
        self,
        *,
        data_dir: Path,
        plugin_root: Path,
        settings,
        broadcast,
        runtime: RuntimeJob,
        discover=discovery.scan,
        tree=discovery.tree,
        list_dirs=discovery.list_dirs,
        spawn=asyncio.create_subprocess_exec,
        clock=time.monotonic,
        home=HOME,
        model_ready=lambda: True,
        paused=lambda: False,
        check_disk=None,
        push_status=None,
    ):
        self.data_dir, self.plugin_root, self.home = data_dir, plugin_root, home
        self.settings, self.broadcast, self.runtime = settings, broadcast, runtime
        self.discover, self.tree, self.list_dirs = discover, tree, list_dirs
        self.spawn, self.clock = spawn, clock
        self.model_ready, self.paused = model_ready, paused
        self.check_disk, self.push_status = check_disk, push_status
        self.ignored = set()
        self._deferred = set()
        self._active_volume = None
        self._scan = None
        self._scans = {}
        self._index = None
        self._starting = None
        self._index_lock = asyncio.Lock()
        self._last = None
        self._last_at = float("-inf")
        self._final = True
        self._mounts = {}

    @staticmethod
    def _error(kind, code, reason):
        return {"t": "error", "for": kind, "code": code, "reason": reason}

    async def _discover(self, volume=None):
        task = self._scans.get(volume)
        if task is None or task.done():
            task = asyncio.create_task(
                asyncio.to_thread(self.discover, home=self.home, volume=volume)
            )
            self._scans[volume] = task
        scan = await asyncio.shield(task)
        self._scan = scan
        return scan

    async def handle(self, message: dict) -> dict:
        kind = message["t"]
        try:
            if kind in ("runtime_status", "runtime_install", "runtime_pause"):
                method = {
                    "runtime_status": self.runtime.status,
                    "runtime_install": self.runtime.start,
                    "runtime_pause": self.runtime.pause,
                }[kind]
                return await method()
            if kind == "discover_start":
                volume = message.get("volume")
                if volume is not None and (not isinstance(volume, str) or not volume):
                    return self._error(kind, "bad-request", "Invalid discovery volume.")
                scan = await self._discover(volume)
                return {"t": "discover_result", **scan.body, "volume": volume}
            if kind in ("discover_tree", "fs_list"):
                key = "root" if kind == "discover_tree" else "path"
                path = message.get(key)
                if (
                    not isinstance(path, str)
                    or not path
                    or not (Path(path).is_absolute() or path == "~" or path.startswith("~/"))
                ):
                    return self._error(kind, "bad-request", "Pick an absolute folder path.")
                if kind == "discover_tree":
                    scan = self._scan if self._scan is not None else await self._discover()
                    body = await asyncio.to_thread(self.tree, scan, path, home=self.home)
                else:
                    body = await asyncio.to_thread(self.list_dirs, path, home=self.home)
                return {"t": kind, **body}
            if kind == "drive_decision":
                uuid, choice = message.get("uuid"), message.get("choice")
                if not isinstance(uuid, str) or not uuid or choice not in ("scan", "ignore"):
                    return self._error(kind, "bad-request", "Invalid drive decision.")
                if choice == "ignore":
                    self.ignored.add(uuid)
                return {"t": kind, "uuid": uuid, "choice": choice}
            if kind == "index_start":
                volume = message.get("volume")
                if volume is not None and (not isinstance(volume, str) or not volume):
                    return self._error(kind, "bad-request", "Invalid indexing volume.")
                if self._starting is None or self._starting.done():
                    self._starting = asyncio.create_task(self._start_index(volume))
                return await asyncio.shield(self._starting)
            return self._error(kind, "bad-request", "Unknown setup request.")
        except Exception as error:
            code = (
                "runtime-failed"
                if kind.startswith("runtime_") or kind == "index_start"
                else "scan-failed"
            )
            return self._error(kind, code, str(error))

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
                return self._error(
                    "index_start",
                    "no-roots",
                    "No folders are selected. Pick folders in setup first.",
                )
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
        if self._scan is not None:
            roots = {root["path"] for root in self.settings().roots}
            candidates = {c["path"]: c for c in self._scan.body["candidates"]}
            candidates.update({path: tree.candidate for path, tree in self._scan.roots.items()})
            secrets = sum(
                entry["files"]
                for candidate in candidates.values()
                if candidate["path"] in roots
                for entry in candidate["left_out"]
                if entry["rule"] == "secrets"
            )
            if secrets:
                skipped["secrets"] = secrets
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
                    await self.broadcast(
                        self._error(
                            "index_start",
                            "runtime-failed",
                            f"Indexing exited with code {body['exit']}. "
                            f"See {self.data_dir / 'index/reindex.log'}.",
                        )
                    )

                if self._deferred:
                    volume = None if None in self._deferred else sorted(self._deferred)[0]
                    if volume is None:
                        self._deferred.clear()
                    else:
                        self._deferred.remove(volume)
                    await self.kick(volume)

    async def stop(self) -> None:
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
