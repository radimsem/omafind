import asyncio
import copy
import os
import shutil
import signal
import subprocess
import time
from collections import deque
from pathlib import Path

from . import models


class Paused(Exception):
    pass


def gpu_name(run=subprocess.run) -> str | None:
    try:
        result = run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            return None
        name, memory = result.stdout.splitlines()[0].rsplit(",", 1)
        name = name.strip().removeprefix("NVIDIA ").removeprefix("GeForce ")
        return f"{name} {round(float(memory) / 1024)} GB"
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


class RuntimeJob:
    def __init__(
        self,
        *,
        data_dir: Path,
        plugin_root: Path,
        broadcast,
        spawn=asyncio.create_subprocess_exec,
        download=models.download,
        valid=models.verify,
        gpu=gpu_name,
        clock=time.monotonic,
    ):
        self.data_dir, self.plugin_root = data_dir, plugin_root
        self.broadcast, self.spawn = broadcast, spawn
        self.download, self.valid, self.gpu, self.clock = download, valid, gpu, clock
        self._message = {
            "t": "runtime_progress",
            "state": "idle",
            "step": None,
            "file": None,
            "done": 0,
            "total": round(sum(f.size for f in models.FILES) / 1e6),
            "unit": "MB",
            "left_seconds": None,
            "reason": None,
            "build": {
                "state": "wait",
                "seconds": None,
                "tag": "b11461",
                "backend": "Vulkan",
                "gpu": None,
            },
            "files": {
                key: {
                    "name": file.name,
                    "state": "wait",
                    "done": 0,
                    "total": round(file.size / 1e6),
                }
                for key, file in zip(("model", "mmproj"), models.FILES, strict=True)
            },
        }
        self._bytes = {f.name: 0 for f in models.FILES}
        self._samples = deque()
        self._task = self._process = None
        self._paused = self._stopping = False
        self._last_push = float("-inf")
        self._verified = None
        self._status_lock = asyncio.Lock()
        self._gpu_read = False

    def snapshot(self) -> dict:
        return copy.deepcopy(self._message)

    def _runtime_exists(self):
        return (
            os.access(self.data_dir / "runtime/bin/llama-server", os.X_OK)
            and (self.data_dir / "runtime/BUILD").is_file()
        )

    def _signature(self):
        signature = []
        for file in models.FILES:
            try:
                stat = (self.data_dir / "model" / file.name).stat()
                signature.append((stat.st_size, stat.st_mtime_ns))
            except FileNotFoundError:
                signature.append(None)
        return tuple(signature)

    async def status(self) -> dict:
        async with self._status_lock:
            if self._message["state"] == "running":
                return self.snapshot()
            if not self._gpu_read:
                self._message["build"]["gpu"] = await asyncio.to_thread(self.gpu)
                self._gpu_read = True
            signature = await asyncio.to_thread(self._signature)
            if signature != self._verified:
                verified = await asyncio.to_thread(self.valid, self.data_dir / "model")
                for key, file in zip(("model", "mmproj"), models.FILES, strict=True):
                    ok = verified.get(file.name, False)
                    if (
                        not ok
                        and self._message["state"] == "paused"
                        and self._message["files"][key]["state"] in ("run", "verify")
                    ):
                        continue
                    self._message["files"][key]["state"] = "ok" if ok else "wait"
                    self._bytes[file.name] = file.size if ok else 0
                    self._message["files"][key]["done"] = round(self._bytes[file.name] / 1e6)
                self._verified = signature
            if self._runtime_exists():
                self._message["build"]["state"] = "ok"
            elif self._message["build"]["state"] == "ok":
                self._message["build"]["state"] = "wait"
            self._message["done"] = round(sum(self._bytes.values()) / 1e6)
            if self._message["build"]["state"] == "ok" and all(
                f["state"] == "ok" for f in self._message["files"].values()
            ):
                self._message.update(state="done", step=None, file=None, reason=None)
            elif self._message["state"] == "done":
                self._message.update(state="idle", step=None, file=None)
            return self.snapshot()

    async def _push(self, *, changed=False):
        now = self.clock()
        if not self._stopping and (changed or now - self._last_push >= 0.5):
            self._last_push = now
            await self.broadcast(self.snapshot())

    async def start(self) -> dict:
        async with self._status_lock:
            if self._message["state"] in ("running", "done"):
                return self.snapshot()
            self._paused = self._stopping = False
            self._samples.clear()
            self._message.update(state="running", reason=None, left_seconds=None)
            self._loop = asyncio.get_running_loop()
            self._task = asyncio.create_task(self._launch())
            return self.snapshot()

    async def _launch(self):
        await self._push(changed=True)
        await self._run()

    async def _scope_available(self):
        if not shutil.which("systemd-run") or os.environ.get("OMAFIND_BUILD_MEMORY_MAX") == "0":
            return False
        process = await self.spawn(
            "systemctl",
            "--user",
            "show-environment",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return await process.wait() == 0

    async def _build(self):
        if self._runtime_exists() or self._message["build"]["state"] == "ok":
            self._message["build"]["state"] = "ok"
            return
        if not await self._scope_available():
            raise RuntimeError(
                "Cannot build safely: the systemd user memory scope is unavailable. "
                "Run bin/omafind build-runtime in a user session."
            )
        if self._paused:
            raise Paused
        self._message.update(step="build", file=None)
        self._message["build"]["state"] = "run"
        await self._push(changed=True)
        started = self.clock()
        env = {**os.environ, "OMAFIND_DATA_DIR": str(self.data_dir)}
        env.pop("OMAFIND_BUILD_SCOPED", None)
        self._process = await self.spawn(
            str(self.plugin_root / "scripts/build-runtime.sh"),
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        if self._paused:
            self._terminate()
        lines = deque(maxlen=20)

        async def finish():
            while line := await self._process.stderr.readline():
                lines.append(line.decode(errors="replace").strip())
            return await self._process.wait()

        finishing = asyncio.create_task(finish())
        while not finishing.done():
            await asyncio.wait({finishing}, timeout=0.5)
            if not finishing.done():
                self._message["build"]["seconds"] = round(self.clock() - started)
                await self._push()
        code = await finishing
        self._process = None
        if self._paused:
            raise Paused
        if code:
            self._message["build"]["state"] = "failed"
            last = next((line for line in reversed(lines) if line), f"exit {code}")
            raise RuntimeError(
                f"The runtime build failed: {last}. "
                "Run bin/omafind build-runtime in a terminal for the full log."
            )
        self._message["build"].update(state="ok", seconds=round(self.clock() - started))
        await self._push(changed=True)

    def _progress(self, name, done, total):
        if self._paused:
            raise Paused
        future = asyncio.run_coroutine_threadsafe(self._chunk(name, done, total), self._loop)
        future.result()
        if self._paused:
            raise Paused

    async def _chunk(self, name, done, total):
        key = next(key for key, file in self._message["files"].items() if file["name"] == name)
        file = self._message["files"][key]
        state = "verify" if done == total else "run"
        changed = file["state"] != state or self._message["file"] != key
        file.update(state=state, done=round(done / 1e6), total=round(total / 1e6))
        self._bytes[name] = done
        done_bytes = sum(self._bytes.values())
        self._message.update(file=key, done=round(done_bytes / 1e6))
        now = self.clock()
        self._samples.append((now, done_bytes))
        while len(self._samples) > 1 and now - self._samples[0][0] > 10:
            self._samples.popleft()
        elapsed = now - self._samples[0][0]
        rate = (done_bytes - self._samples[0][1]) / elapsed if elapsed >= 2 else 0
        self._message["left_seconds"] = (
            round((sum(f.size for f in models.FILES) - done_bytes) / rate) if rate > 0 else None
        )
        await self._push(changed=changed)

    async def _run(self):
        try:
            if not self._gpu_read:
                self._message["build"]["gpu"] = await asyncio.to_thread(self.gpu)
                self._gpu_read = True
            await self._build()
            if self._paused:
                raise Paused
            self._message.update(step="download", file=None)
            await self._push(changed=True)
            await asyncio.to_thread(self.download, self.data_dir / "model", progress=self._progress)
            if self._paused:
                raise Paused
            verified = await asyncio.to_thread(self.valid, self.data_dir / "model")
            for key, file in zip(("model", "mmproj"), models.FILES, strict=True):
                if not verified.get(file.name, False):
                    raise RuntimeError(
                        f"Model sha256 mismatch: {file.name}. Press Resume to download it again."
                    )
                self._bytes[file.name] = file.size
                self._message["files"][key].update(state="ok", done=round(file.size / 1e6))
                await self._push(changed=True)
            self._verified = await asyncio.to_thread(self._signature)
            self._message.update(
                state="done", step=None, file=None, done=self._message["total"], left_seconds=None
            )
        except Paused:
            self._message.update(state="paused", left_seconds=None)
        except Exception as error:
            reason = str(error)
            if reason.startswith("Model sha256 mismatch:") and "Press Resume" not in reason:
                reason += ". Press Resume to download it again."
            self._message.update(state="failed", reason=reason, left_seconds=None)
        await self._push(changed=True)

    def _terminate(self):
        if self._process is not None and self._process.returncode is None:
            try:
                os.killpg(self._process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    async def pause(self) -> dict:
        if self._task is not None and not self._task.done():
            self._paused = True
            self._terminate()
            await asyncio.shield(self._task)
        return self.snapshot()

    async def stop(self) -> None:
        self._stopping = True
        await self.pause()
