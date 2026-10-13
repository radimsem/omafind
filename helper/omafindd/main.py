import asyncio
import fcntl
import logging
import os
import signal
import sqlite3
import subprocess
import time
from contextlib import closing
from pathlib import Path

from . import build, health, paths, permissions, recovery
from .diskguard import DiskGuard
from .install import RuntimeJob
from .ipc import AlreadyRunning, IpcServer
from .models import Verifier
from .service import SearchService
from .settings import SettingsReader
from .setup import SetupService
from .state import State
from .volumes import Volumes, is_drive, lsblk, parse_lsblk, remap_root
from .watcher import Watcher

logger = logging.getLogger(__name__)
_INDEX_BUSY = object()
_FRESHNESS_ERRORS = (sqlite3.Error, OSError, subprocess.SubprocessError)
_RETRY_FIRST, _RETRY_MAX = 2.0, 30.0


def _freshness_error(step, error):
    logger.warning('Freshness %s failed (%s); retrying.', step, type(error).__name__)
    # The traceback names code, never indexed files or queries.
    logger.debug('Freshness %s traceback', step, exc_info=error)


def Embedder(**kwargs):
    from .embedder import Embedder as RuntimeEmbedder
    return RuntimeEmbedder(**kwargs)


def Adapter(embedder):
    from .embedding import Adapter as RuntimeAdapter
    return RuntimeAdapter(embedder)


class _LazyEmbedder:
    def __init__(self):
        self.instance = None

    @property
    def mode(self):
        return self.instance.mode if self.instance is not None else None

    @property
    def connection_env(self):
        return self.instance.connection_env if self.instance is not None else {}

    async def start(self, mode):
        if self.instance is None:
            self.instance = Adapter(Embedder(
                binary=paths.runtime_bin(), model_dir=paths.model_dir()))
        # Freshness children need the projector; keep query warmups in that same mode.
        await self.instance.start('full')

    async def stop(self):
        if self.instance is not None:
            await self.instance.stop()

    async def embed_query(self, text):
        return await self.instance.embed_query(text)


def _repair(directory):
    paths_to_check = [p for p in (directory / 'index').glob('*.sqlite') if p.name != 'code.sqlite']
    if not paths_to_check:
        return []
    from .store import Store, mounted_volumes, quarantine, quick_check

    mounts = mounted_volumes()
    problems = []
    for path in paths_to_check:
        if quick_check(path):
            continue
        meta = {}
        try:
            with closing(sqlite3.connect(path.absolute().as_uri() + '?mode=ro', uri=True)) as db:
                meta = dict(db.execute('SELECT key,value FROM meta'))
        except sqlite3.Error:
            pass
        try:
            fact = parse_lsblk(lsblk()).get(path.stem)
        except (OSError, ValueError, subprocess.SubprocessError):
            fact = None
        mount = mounts.get(path.stem, Path(meta.get('volume_mount', '/')))
        label = meta.get('volume_label',
                         fact.label if fact is not None and is_drive(fact) else 'root')
        moved = quarantine(path)
        store = Store(path, volume=path.stem, mount=mount, label=label)
        store.close()
        problems.append({'volume': path.stem, 'problem': 'integrity', 'action': 'rebuilt',
                         'moved_to': str(moved), 'at': time.time()})
    return problems


class _Freshness:
    def __init__(self, directory, settings, server, service, report):
        self.directory, self.settings = directory, settings
        self.server, self.service = server, service
        self.report = report
        self.guard = DiskGuard(directory)
        self.paused = None
        self.dirty = {}
        self.retry = {}
        self.pending = set()
        self.volumes = Volumes(lsblk=lsblk, known=self.known, ignored=self.ignored)
        self.watcher = Watcher(on_dirty=self.on_dirty)
        self.watched = None
        self.disk_at = float('-inf')
        self._reconcile_want = None
        self._volume_events = []
        self._disk_event = None
        self.wake = asyncio.Event()

    def known(self, uuid):
        return (self.directory / 'index' / f'{uuid}.sqlite').is_file()

    def ignored(self):
        return set(self.settings().ignored_volumes) | self.server.setup.ignored

    def volume_message(self, volume):
        return {'t': 'volume', 'uuid': volume.uuid, 'label': volume.label, 'fs': volume.fs,
                'size': volume.size, 'mount': str(volume.mount) if volume.mount else None,
                'online': volume.online, 'known': self.known(volume.uuid)}

    def replay(self):
        events = [self.volume_message(v) for v in self.volumes.online().values()
                  if is_drive(v) and not self.known(v.uuid) and v.uuid not in self.ignored()]
        return events + ([self.paused] if self.paused is not None else [])

    async def check_disk(self):
        event = self._disk_event or self.guard.check()
        if event is not None:
            self._disk_event = event
            self.paused = event if event['t'] == 'paused' else None
            await self.server.broadcast(event)
            self._disk_event = None
        return event

    def _reconcile(self, uuid, only, progress):
        descriptor = None
        waiting = False
        try:
            leased = self.service.index_leased
            if not leased and self._reconcile_want is None:
                want = os.open(self.directory / 'index.want', os.O_CREAT | os.O_RDWR, 0o600)
                try:
                    fcntl.flock(want, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BaseException:
                    os.close(want)
                    raise
                self._reconcile_want = want
            descriptor = os.open(self.directory / 'index.lock', os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(descriptor, (fcntl.LOCK_SH if leased else fcntl.LOCK_EX) | fcntl.LOCK_NB)
            return self._reconcile_index(uuid, only, progress)
        except BlockingIOError:
            # Keep intent across ticks so a warm search reader sees it and yields.
            waiting = True
            return _INDEX_BUSY
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if not waiting and self._reconcile_want is not None:
                self._release_reconcile_intent()

    def _release_reconcile_intent(self):
        if self._reconcile_want is not None:
            os.close(self._reconcile_want)
            self._reconcile_want = None

    def _reconcile_index(self, uuid, only, progress):
        from .reconcile import reconcile
        from .store import Store

        mounts = self.service.current_mounts()
        if uuid not in mounts:
            return None
        path = self.directory / 'index' / f'{uuid}.sqlite'
        last, label = None, 'root'
        if path.exists():
            existing = Store.open_existing(path, mounts[uuid])
            try:
                last, label = existing.last_mount, existing.label
            finally:
                existing.close()
        fact = self.volumes.last(uuid)
        if fact is not None and is_drive(fact):
            label = fact.label
            if fact.mount is not None:
                mapping = self.report.setdefault('mounts', {}).setdefault(uuid, {'previous': []})
                if last and str(last) not in mapping['previous']:
                    mapping['previous'].append(str(last))
                mapping['current'] = str(fact.mount)
                health.write(self.directory / 'index/health.json', self.report)
                self.service._mountinfo = None
        roots = [root for root in self.settings().roots if root['volume'] == uuid]
        mapped = [mapped for root in roots if (mapped := remap_root(
            root, mounts, {uuid: last} if last else {})) is not None]
        store = Store(path, volume=uuid, mount=mounts[uuid], label=label)
        try:
            return reconcile(store, mapped, only=only, progress=progress)
        finally:
            store.close()

    async def reconcile(self, uuid, only=None, *, announce=False):
        try:
            async with self.server.setup._index_lock:
                await self._reconcile_locked(uuid, only, announce=announce)
        except _FRESHNESS_ERRORS as error:
            self.defer(uuid, only)
            self._back_off(uuid)
            _freshness_error('reconcile', error)

    def _back_off(self, uuid):
        delay = min(self.retry[uuid][0] * 2, _RETRY_MAX) if uuid in self.retry else _RETRY_FIRST
        self.retry[uuid] = (delay, time.monotonic() + delay)

    async def _reconcile_locked(self, uuid, only=None, *, announce=False):
        if self.server.setup.busy:
            self._release_reconcile_intent()
            self.defer(uuid, only)
            return
        self._release_reconcile_intent()
        await self.service.lease_indexer()
        fact = self.volumes.last(uuid)
        label = fact.label if fact else uuid
        loop = asyncio.get_running_loop()
        updates = asyncio.Queue()
        last_at = float('-inf')
        final = [0, 0]

        def progress(done, total):
            nonlocal last_at
            final[:] = [done, total]
            now = time.monotonic()
            if now - last_at >= .5 and done != total:
                last_at = now
                loop.call_soon_threadsafe(updates.put_nowait, (done, total))

        async def publish():
            while True:
                done, total = await updates.get()
                try:
                    await self.server.broadcast({'t': 'reconcile', 'uuid': uuid, 'label': label,
                                                 'done': done, 'total': total})
                except _FRESHNESS_ERRORS as error:
                    self.defer(uuid, only)
                    _freshness_error('progress', error)

        publisher = asyncio.create_task(publish()) if announce else None
        work = asyncio.create_task(asyncio.to_thread(
            self._reconcile, uuid, only, progress if announce else None))
        try:
            result = await asyncio.shield(work)
            if result is _INDEX_BUSY:
                self.defer(uuid, only)
                return
            self.retry.pop(uuid, None)
            if result is not None and result.queued:
                self.pending.add(uuid)
            if announce and result is not None:
                await asyncio.sleep(0)
                await self.server.broadcast({'t': 'reconcile', 'uuid': uuid, 'label': label,
                                             'done': final[1], 'total': final[1]})
            await self.server.push_status(force=True)
        except asyncio.CancelledError:
            await asyncio.gather(work, return_exceptions=True)
            raise
        finally:
            if publisher is not None:
                publisher.cancel()
                await asyncio.gather(publisher, return_exceptions=True)
            if not self.pending:
                await self.service.release_indexer()

    async def spawn_indexer(self, *argv, **kwargs):
        env = await self.service.lease_indexer()
        child_env = dict(kwargs.get('env', os.environ))
        for key in ('OMAFIND_EMBED_URL', 'OMAFIND_EMBED_KEY'):
            child_env.pop(key, None)
        kwargs['env'] = {**child_env, **(env or {})}
        try:
            child = await asyncio.create_subprocess_exec(*argv, **kwargs)
        except BaseException:
            await self.service.release_indexer()
            raise
        if env is not None:
            self.service.watch_indexer(child)
        return child

    def defer(self, uuid, only):
        if uuid not in self.dirty:
            self.dirty[uuid] = None if only is None else set(only)
        elif only is None:
            self.dirty[uuid] = None
        elif self.dirty[uuid] is not None:
            self.dirty[uuid].update(only)

    async def on_dirty(self, root, dirs):
        self.defer(root['volume'], dirs)
        self.wake.set()

    async def on_events(self, events):
        if events:
            self.wake.set()
        self._volume_events.extend(events)
        pending, self._volume_events = self._volume_events, []
        for event in pending:
            try:
                self.service._mountinfo = None
                if event.kind == 'returned':
                    self.defer(event.volume.uuid, None)
                await self.server.broadcast(self.volume_message(event.volume))
                if event.kind == 'gone':
                    await self.server.push_status(force=True)
            except _FRESHNESS_ERRORS as error:
                self._volume_events.append(event)
                _freshness_error('volume', error)

    async def tick(self):
        try:
            await self._tick()
        except _FRESHNESS_ERRORS as error:
            _freshness_error('tick', error)
        finally:
            if not self.server.setup.busy:
                await self.service.release_indexer()

    async def _tick(self):
        if self.server.setup.busy:
            self._release_reconcile_intent()
        await self.on_events([])
        roots = self.settings().roots
        if roots != self.watched:
            internal = [root for root in roots if not (
                (fact := self.volumes.last(root['volume'])) is not None
                and (fact.removable or is_drive(fact))) and not any(
                    Path(root['path']).is_relative_to(base)
                    for base in (Path('/run/media'), Path('/media'), Path('/mnt')))]
            try:
                self.watcher.loop = asyncio.get_running_loop()
                watch = asyncio.create_task(asyncio.to_thread(self.watcher.watch, internal))
                try:
                    await asyncio.shield(watch)
                except asyncio.CancelledError:
                    await asyncio.gather(watch, return_exceptions=True)
                    raise
                self.watched = roots
            except _FRESHNESS_ERRORS as error:
                _freshness_error('watcher', error)
        now = time.monotonic()
        if now - self.disk_at >= 30:
            try:
                event = await self.check_disk()
                self.disk_at = now
                if event is not None and event['t'] == 'resumed':
                    self.pending.add(None)
            except _FRESHNESS_ERRORS as error:
                _freshness_error('disk', error)
        now = time.monotonic()
        due = [uuid for uuid in self.dirty if uuid not in self.retry or self.retry[uuid][1] <= now]
        if not self.server.setup.busy and due:
            uuid = due[0]
            only = self.dirty.pop(uuid)
            try:
                await self.reconcile(uuid, only, announce=only is None)
            except _FRESHNESS_ERRORS as error:
                self.defer(uuid, only)
                self._back_off(uuid)
                _freshness_error('reconcile', error)
        if self.pending and not self.server.setup.busy and not self.guard.paused \
                and self.server.state.model == 'ready':
            uuid = None if None in self.pending else sorted(self.pending)[0]
            try:
                self._release_reconcile_intent()
                await self.server.setup.kick(uuid)
                self.pending.discard(uuid)
            except _FRESHNESS_ERRORS as error:
                _freshness_error('kick', error)


async def _wait_for_work(stop, wake, interval):
    waits = [asyncio.create_task(event.wait()) for event in (stop, wake)]
    try:
        await asyncio.wait(waits, timeout=interval, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in waits:
            task.cancel()
        await asyncio.gather(*waits, return_exceptions=True)


async def _serve(manifest: Path | None = None, *, interval: float = 0.5) -> int:
    manifest = manifest if manifest is not None else paths.manifest_path()
    if not manifest.is_file():
        return 0
    directory = paths.data_dir()
    permissions.fix_dirs(directory)
    started = recovery.begin(directory)
    settings = SettingsReader(paths.shell_json_path())
    verifier = Verifier()
    detected = await asyncio.to_thread(State.detect, verifier)
    problems = await asyncio.to_thread(_repair, directory)
    report = health.read(directory / 'index/health.json')
    report.update(started=time.time(), recovery={
        'clean': started.clean, 'mode': 'none' if started.clean else 'reconcile',
        'journal_retried': started.journal_files}, model={
            'verified': detected.model == 'ready', 'files': verifier.files_report()},
        problems=report.get('problems', []) + problems)
    health.write(directory / 'index/health.json', report)
    plugin_root = Path(__file__).resolve().parents[2]
    try:
        detected.build = await asyncio.to_thread(build.fingerprint, plugin_root)
    except (OSError, ValueError) as error:
        # An empty build differs from every plugin build, so the plugin reruns setup once.
        logger.warning('Cannot fingerprint %s: %s', plugin_root, error)
    server = IpcServer(paths.socket_path(), detected)
    service = SearchService(directory / 'index', settings.read, _LazyEmbedder(), server.state)
    server.service = service
    runtime = RuntimeJob(data_dir=directory, plugin_root=plugin_root, broadcast=server.broadcast)
    freshness = _Freshness(directory, settings.read, server, service, report)
    async def push_status(**kwargs):
        if hasattr(server, 'push_status'):
            await server.push_status(**kwargs)

    server.setup = SetupService(data_dir=directory, plugin_root=plugin_root, settings=settings.read,
                                broadcast=server.broadcast, runtime=runtime,
                                model_ready=lambda: server.state.model == 'ready',
                                paused=lambda: freshness.guard.paused,
                                check_disk=freshness.check_disk,
                                spawn=freshness.spawn_indexer,
                                push_status=push_status)
    server.replay = freshness.replay
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    signals = (signal.SIGINT, signal.SIGTERM)
    for signum in signals:
        loop.add_signal_handler(signum, stop.set)
    tasks = []
    clean = False
    try:
        await server.start()
        try:
            await asyncio.to_thread(freshness.volumes.snapshot)
        except (OSError, ValueError, subprocess.SubprocessError):
            logger.warning('Cannot read volume facts; mount polling will retry.')
        for volume in freshness.volumes.online().values():
            if not is_drive(volume):
                continue
            if freshness.known(volume.uuid):
                freshness.defer(volume.uuid, None)
            elif volume.uuid not in freshness.ignored():
                await server.broadcast(freshness.volume_message(volume))
        tasks = [asyncio.create_task(freshness.volumes.run(freshness.on_events)),
                 asyncio.create_task(freshness.watcher.run())]
        if not started.clean:
            for root in settings.read().roots:
                freshness.defer(root['volume'], None)
        for problem in problems:
            freshness.defer(problem['volume'], None)
        if started.journal_files:
            freshness.pending.add(None)
        while manifest.is_file() and not stop.is_set():
            freshness.wake.clear()
            await service.yield_to_indexer()
            detected = await asyncio.to_thread(State.detect, verifier)
            await server.state.update(runtime=detected.runtime, model=detected.model)
            model = {'verified': detected.model == 'ready', 'files': verifier.files_report()}
            if model != report['model']:
                report['model'] = model
                health.write(directory / 'index/health.json', report)
            await freshness.tick()
            await _wait_for_work(stop, freshness.wake, interval)
        clean = True
        return 0
    except AlreadyRunning as error:
        logger.error('%s', error)
        return 1
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        freshness.watcher.stop()
        if (want := getattr(freshness, '_reconcile_want', None)) is not None:
            os.close(want)
        await server.stop()
        await service.stop()
        for signum in signals:
            loop.remove_signal_handler(signum)
        if clean:
            recovery.end(directory)


def run() -> int:
    level = os.environ.get('OMAFINDD_LOG', 'INFO').upper()
    logging.basicConfig(level=level if level in logging.getLevelNamesMapping() else 'INFO')
    try:
        return asyncio.run(_serve())
    except (OSError, ValueError) as error:
        logger.error('%s', error)
        return 1
    except KeyboardInterrupt:
        return 0
