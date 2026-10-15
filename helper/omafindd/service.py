import asyncio
import fcntl
import os
import sqlite3
from pathlib import Path

from .code import configured_roots


def mounted_volumes():
    from .store import mounted_volumes as resolve
    return resolve()


def volume_for(path, **kwargs):
    from .store import volume_for as resolve
    return resolve(path, **kwargs)


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
        self._searcher = None
        self._databases = {}
        self._idle_task = None
        self._warm_task = None
        self._lock = asyncio.Lock()
        self._index_lock = None
        self._lease_want = None
        self._lease_child = None
        self._lease_task = None
        self._mountinfo = None
        self._mount_files = None
        self._mount_roots = None
        self._mounts = {}

    @property
    def searcher(self):
        if self._searcher is None:
            from .search import Searcher
            self._searcher = Searcher([], self.embedder, start=self._start_query,
                                      code_directory=self.directory)
        return self._searcher

    @searcher.setter
    def searcher(self, value):
        self._searcher = value

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
        if self.index_leased:
            return False
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
        from .embedder import EmbeddingError
        async with self._lock:
            if self.index_leased:
                if self.embedder.mode != 'full':
                    raise EmbeddingError('Shared embedding server is not running')
                return
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
        task, self._warm_task = self._warm_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with self._lock:
            if self.index_leased:
                return False
            await self._stop_locked()
            return True

    @property
    def index_leased(self):
        return self._lease_want is not None

    async def lease_indexer(self):
        from .embedder import EmbeddingError

        async with self._lock:
            if self.index_leased:
                if self._lease_child is not None and self._lease_child.returncode is not None:
                    self._lease_child = None
                return self.embedder.connection_env
            if self.state.model != 'ready':
                return None
            self.directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            want = os.open(self.directory.parent / 'index.want', os.O_CREAT | os.O_RDWR, 0o600)
            try:
                # Retain both shared locks so external indexers cannot take server ownership.
                fcntl.flock(want, fcntl.LOCK_SH | fcntl.LOCK_NB)
                if self._index_lock is None:
                    self._index_lock = self._probe_lock()
                self._cancel_idle()
                await self.embedder.start('full')
                env = self.embedder.connection_env
                if self.embedder.mode != 'full' or not env.get('OMAFIND_EMBED_URL'):
                    raise EmbeddingError('Embedding server cannot be shared')
                await self.state.update(embedder=self.embedder.mode)
                self._lease_want = want
                return env
            except (EmbeddingError, OSError):
                await self._stop_locked()
                await self.state.update(embedder='stopped')
                return None
            except BaseException:
                await self._stop_locked()
                raise
            finally:
                if self._lease_want != want:
                    os.close(want)

    async def release_indexer(self):
        async with self._lock:
            self._release_indexer_locked()

    def _release_indexer_locked(self):
        if self._lease_want is None:
            return
        os.close(self._lease_want)
        self._lease_want = None
        self._lease_child = None
        if self.embedder.mode is not None:
            self._arm_idle()

    def watch_indexer(self, child):
        self._lease_child = child
        self._lease_task = asyncio.create_task(self._wait_indexer(child))

    async def _wait_indexer(self, child):
        try:
            await child.wait()
        finally:
            async with self._lock:
                if self._lease_child is child:
                    self._release_indexer_locked()

    def _warming(self, mode):
        if self._warm_task is None or self._warm_task.done():
            self._warm_task = asyncio.create_task(self._warm(mode))
        return self._warm_task

    async def _warm(self, mode):
        from .embedder import EmbeddingError

        try:
            await self._start(mode)
        except (EmbeddingError, OSError) as error:
            await self.state.update(embedder="stopped")
            return str(error) or "the embedding server did not start"
        await self.state.update(embedder=self.embedder.mode or "stopped")
        if self.embedder.mode is not None:
            self._arm_idle()
        return None

    async def _start_query(self, mode):
        from .embedder import EmbeddingError

        if self._warm_task is not None and self._warm_task.done():
            if reason := self._warm_task.result():
                self._warm_task = None
                raise EmbeddingError(reason)
        if self.embedder.ready(mode):
            return
        task = self._warming(mode)
        # An already warm server can finish in one turn; a cold load stays in the background.
        await asyncio.sleep(0)
        if not task.done():
            raise EmbeddingError("the embedding server is starting")
        if reason := task.result():
            raise EmbeddingError(reason)

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
        if not self.index_leased and self._index_lock is not None and self._indexing():
            self._cancel_idle()
            if await self._stop():
                await self.state.update(embedder="stopped")

    def current_mounts(self):
        mountinfo = Path("/proc/self/mountinfo").read_bytes()
        files = set(self.directory.glob("*.sqlite")) - {self.directory / "code.sqlite"}
        roots = self.settings().roots
        if (mountinfo != self._mountinfo or files != self._mount_files
                or roots != self._mount_roots):
            mounts = dict(self.mounts_resolver())
            for path in [self.directory.parent, *(Path(root["path"])
                                                  for root in self.settings().roots)]:
                try:
                    volume, mount = self.volume_resolver(path, mounts=mounts)
                except OSError:
                    continue
                mounts[volume] = mount
            self._mountinfo, self._mount_files, self._mounts = mountinfo, files, mounts
            self._mount_roots = roots
        return self._mounts

    def _refresh(self):
        from .store import Store

        self.searcher.code_roots = configured_roots(self.settings)
        files = set(self.directory.glob("*.sqlite")) - {self.directory / "code.sqlite"}
        mounts = self.current_mounts()
        for path in self._databases.keys() - files:
            self._databases.pop(path).close()
        for path in files:
            if path not in self._databases:
                try:
                    store = Store.open_existing(path.absolute(), mounts.get(path.stem, Path("/")))
                except (sqlite3.Error, KeyError):
                    self._mount_files = self._mount_files - {path}
                    continue
                self._databases[path] = store
            store = self._databases[path]
            store.online = store.volume in mounts
            store.mount = mounts.get(store.volume, store.last_mount or Path("/"))
        self.searcher.stores = list(self._databases.values())

    def _cancel_idle(self):
        if self._idle_task is not None:
            self._idle_task.cancel()
            self._idle_task = None

    def _arm_idle(self):
        self._cancel_idle()
        if not self.index_leased:
            self._idle_task = asyncio.create_task(self._idle(self.settings().warm_minutes * 60))

    async def _idle(self, seconds):
        await asyncio.sleep(seconds)
        if await self._stop():
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
        from .embedder import EmbeddingError
        from .search import PREFIXES

        indexing = self._indexing()
        if indexing:
            await self._stop()
        if message["t"] == "warm":
            try:
                if indexing:
                    raise EmbeddingError("indexing in progress")
                if reason := await asyncio.shield(self._warming("text")):
                    raise EmbeddingError(reason)
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
        kinds = message.get("kinds")
        if (
            type(seq) is not int
            or not isinstance(q, str)
            or not isinstance(legs, list)
            or not legs
            or any(leg not in ("words", "meaning") for leg in legs)
            or type(limit) is not int
            or not 1 <= limit <= 200
            or ("kinds" in message and (not isinstance(kinds, list)
                or any(not isinstance(kind, str) or kind not in PREFIXES.values()
                       for kind in kinds)))
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
            unverified = self.state.model != "ready"
            reply = await self.searcher.search(
                q, legs=["words"] if indexing or unverified else legs, limit=limit, seq=seq,
                kinds=kinds
            )
            if unverified:
                reply["legs"] = ["words"]
                reply["degraded"] = "embedding model failed verification"
            elif indexing or reply["degraded"] == "indexing in progress":
                if "words" not in reply["legs"]:
                    reply = await self.searcher.search(q, legs=["words"], limit=limit, seq=seq,
                                                       kinds=kinds)
                reply["legs"] = ["words"]
                reply["degraded"] = "indexing in progress"
            elif reply["degraded"] == "the embedding server is starting":
                if "words" not in reply["legs"]:
                    reply = await self.searcher.search(q, legs=["words"], limit=limit, seq=seq,
                                                       kinds=kinds)
                reply["legs"] = ["words"]
                reply["degraded"] = "the embedding server is starting"
        except FileNotFoundError as error:
            return {"t": "error", "seq": seq, "code": "no-index", "reason": str(error)}
        return reply

    async def stop(self):
        if self._lease_task is not None:
            await self._lease_task
            self._lease_task = None
        # A cold warm-up holds self._lock until it is cancelled.
        warm, self._warm_task = self._warm_task, None
        if warm is not None:
            warm.cancel()
            await asyncio.gather(warm, return_exceptions=True)
        await self.release_indexer()
        task = self._idle_task
        self._cancel_idle()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await self._stop()
        for store in self._databases.values():
            store.close()
        self._databases.clear()
