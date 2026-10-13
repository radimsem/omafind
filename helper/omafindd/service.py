import asyncio
import fcntl
import os
import sqlite3
from pathlib import Path

from .code import configured_roots
from .embedder import EmbeddingError
from .search import Searcher
from .store import Store, mounted_volumes, volume_for


class SearchService:
    def __init__(
        self,
        directory: Path,
        settings,
        embedder,
        state,
        *,
        volume_resolver=volume_for,
        mounts_resolver=mounted_volumes,
    ):
        self.directory, self.settings, self.embedder, self.state = (
            directory,
            settings,
            embedder,
            state,
        )
        self.volume_resolver = volume_resolver
        self.mounts_resolver = mounts_resolver
        self.searcher = Searcher([], embedder, start=self._start, code_directory=directory)
        self._databases = {}
        self._idle_task = None
        self._lock = asyncio.Lock()
        self._index_lock = None
        self._mountinfo = None
        self._mount_files = None
        self._mounts = {}

    def _probe_lock(self):
        self.directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        intent = os.open(self.directory.parent / "index.want", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(intent, fcntl.LOCK_SH | fcntl.LOCK_NB)
            descriptor = os.open(
                self.directory.parent / "index.lock", os.O_CREAT | os.O_RDWR, 0o600
            )
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BaseException:
                os.close(descriptor)
                raise
            return descriptor
        finally:
            os.close(intent)

    def _indexing(self):
        try:
            descriptor = self._probe_lock()
        except BlockingIOError:
            return True
        os.close(descriptor)
        return False

    def _release_lock(self):
        if self._index_lock is not None:
            os.close(self._index_lock)
            self._index_lock = None

    async def _start(self, mode):
        async with self._lock:
            if self._index_lock is None:
                try:
                    self._index_lock = self._probe_lock()
                except BlockingIOError as error:
                    raise EmbeddingError("indexing in progress") from error
            elif self._indexing():
                self._cancel_idle()
                await self._stop_locked()
                await self.state.update(embedder="stopped")
                raise EmbeddingError("indexing in progress")
            try:
                await self.embedder.start(mode)
            except BaseException:
                if self.embedder.mode is None:
                    self._release_lock()
                raise

    async def _stop(self):
        async with self._lock:
            await self._stop_locked()

    async def _stop_locked(self):
        stopping = asyncio.create_task(self.embedder.stop())
        try:
            await asyncio.shield(stopping)
        except asyncio.CancelledError:
            await stopping
            self._release_lock()
            raise
        else:
            self._release_lock()

    async def yield_to_indexer(self):
        async with self._lock:
            if self._index_lock is not None and self._indexing():
                self._cancel_idle()
                await self._stop_locked()
                await self.state.update(embedder="stopped")

    def _refresh(self):
        self.searcher.code_roots = configured_roots(self.settings)
        files = set(self.directory.glob("*.sqlite")) - {self.directory / "code.sqlite"}
        mountinfo = Path("/proc/self/mountinfo").read_bytes()
        if mountinfo != self._mountinfo or files != self._mount_files:
            mounts = dict(self.mounts_resolver())
            roots = self.settings().roots
            for path in [self.directory.parent, *(Path(root["path"]) for root in roots)]:
                try:
                    volume, mount = self.volume_resolver(path, mounts=mounts)
                except OSError:
                    continue
                mounts[volume] = mount
            self._mountinfo, self._mount_files, self._mounts = mountinfo, files, mounts
        mounts = self._mounts
        for path in self._databases.keys() - files:
            self._databases.pop(path).close()
        for path in files:
            if path not in self._databases:
                try:
                    store = Store.open_existing(path.absolute(), mounts.get(path.stem, Path("/")))
                except (sqlite3.Error, KeyError):
                    self._mount_files = self._mount_files - {path}
                    continue
                if store.volume not in mounts:
                    store.close()
                    continue
                store.mount = mounts[store.volume]
                self._databases[path] = store
            else:
                store = self._databases[path]
                if store.volume in mounts:
                    store.mount = mounts[store.volume]
        self.searcher.stores = list(self._databases.values())

    def _cancel_idle(self):
        if self._idle_task is not None:
            self._idle_task.cancel()
            self._idle_task = None

    def _arm_idle(self):
        self._cancel_idle()
        self._idle_task = asyncio.create_task(self._idle(self.settings().warm_minutes * 60))

    async def _idle(self, seconds):
        await asyncio.sleep(seconds)
        await self._stop()
        await self.state.update(embedder="stopped")

    async def handle(self, message: dict) -> dict:
        self._cancel_idle()
        try:
            return await self._handle(message)
        finally:
            mode = self.embedder.mode
            await self.state.update(embedder=mode or "stopped")
            if mode is not None:
                self._arm_idle()

    async def _handle(self, message: dict) -> dict:
        indexing = self._indexing()
        if indexing:
            await self._stop()
        if message["t"] == "warm":
            try:
                if indexing:
                    raise EmbeddingError("indexing in progress")
                await self._start("text")
                await self.state.update(embedder="text")
                return self.state.message()
            except (EmbeddingError, OSError) as error:
                await self.state.update(embedder="stopped")
                return {
                    "t": "warm_failed",
                    "reason": str(error) or "the embedding server did not start",
                }
        seq = message.get("seq")
        q, legs = message.get("q"), message.get("legs", ["words", "meaning"])
        limit = message.get("limit", self.settings().max_results)
        if (
            type(seq) is not int
            or not isinstance(q, str)
            or not isinstance(legs, list)
            or not legs
            or any(leg not in ("words", "meaning") for leg in legs)
            or type(limit) is not int
            or not 1 <= limit <= 200
        ):
            return {
                "t": "error",
                "seq": seq,
                "code": "bad-request",
                "reason": "Invalid search arguments",
            }
        try:
            self._refresh()
            if not indexing and self._indexing():
                indexing = True
                await self._stop()
            reply = await self.searcher.search(
                q, legs=["words"] if indexing else legs, limit=limit, seq=seq
            )
            if indexing or reply["degraded"] == "indexing in progress":
                if "words" not in reply["legs"]:
                    reply = await self.searcher.search(q, legs=["words"], limit=limit, seq=seq)
                reply["legs"] = ["words"]
                reply["degraded"] = "indexing in progress"
        except FileNotFoundError as error:
            return {"t": "error", "seq": seq, "code": "no-index", "reason": str(error)}
        return reply

    async def stop(self):
        task = self._idle_task
        self._cancel_idle()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await self._stop()
        for store in self._databases.values():
            store.close()
        self._databases.clear()
