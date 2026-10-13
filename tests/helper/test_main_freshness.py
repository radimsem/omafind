import asyncio
import fcntl
import itertools
import os
import socket
import sqlite3
import subprocess
import threading
from types import SimpleNamespace

import pytest
from omafindd import main
from omafindd.main import _Freshness
from omafindd.reconcile import Reconciled
from omafindd.store import Store
from omafindd.volumes import Volume, VolumeEvent


@pytest.fixture
def freshness(tmp_path, monkeypatch):
    async def nothing(*args, **kwargs):
        pass

    setup = SimpleNamespace(busy=False, ignored=set(), _index_lock=asyncio.Lock(), kick=nothing)
    server = SimpleNamespace(setup=setup, state=SimpleNamespace(model='ready'),
                             broadcast=nothing, push_status=nothing)
    settings = SimpleNamespace(roots=[], ignored_volumes=())
    service = SimpleNamespace(current_mounts=lambda: {'v': tmp_path}, _mountinfo=None,
                              index_leased=False, lease_indexer=nothing, release_indexer=nothing)
    result = _Freshness(tmp_path, lambda: settings, server, service, {})
    result.real_to_thread = asyncio.to_thread

    async def inline(callback, *args, **kwargs):
        return callback(*args, **kwargs)

    monkeypatch.setattr(asyncio, 'to_thread', inline)
    monkeypatch.setattr(result.watcher, 'watch', lambda roots: None)
    monkeypatch.setattr(result.guard, 'free_bytes', lambda: 3_000_000_000)
    yield result
    if getattr(result, '_reconcile_want', None) is not None:
        os.close(result._reconcile_want)


async def test_watcher_setup_runs_off_event_loop(freshness, monkeypatch):
    left, right = socket.socketpair()
    try:
        try:
            left.send(b'x')
        except PermissionError as error:
            pytest.skip(f'Asyncio thread wakeup is blocked: {error}')
    finally:
        left.close()
        right.close()
    monkeypatch.setattr(asyncio, 'to_thread', freshness.real_to_thread)
    threads = []
    monkeypatch.setattr(freshness.watcher, 'watch',
                        lambda roots: threads.append(threading.get_ident()))
    await freshness.tick()
    assert threads and threads[0] != threading.get_ident()


async def test_loop_wakes_without_waiting_a_tick_after_on_dirty(freshness, monkeypatch):
    reconciled = []
    monkeypatch.setattr(freshness, '_reconcile',
                        lambda uuid, only, progress: reconciled.append((uuid, only)))
    stop = asyncio.Event()
    waiting = asyncio.create_task(main._wait_for_work(stop, freshness.wake, 60))
    try:
        await asyncio.sleep(0)
        await freshness.on_dirty({'volume': 'v'}, {freshness.directory})
        await asyncio.wait_for(waiting, .1)
        await freshness.tick()
        assert reconciled == [('v', {freshness.directory})]
    finally:
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)


async def test_serve_loop_wakes_on_dirty_before_tick_timeout(tmp_path, monkeypatch, freshness):
    manifest = tmp_path / 'manifest.json'
    manifest.touch()
    waiting, reconciled = asyncio.Event(), asyncio.Event()
    instances = []
    wait_for_work = main._wait_for_work

    async def wait(stop, wake, interval):
        waiting.set()
        await wait_for_work(stop, wake, interval)

    async def forever(*args):
        await asyncio.Event().wait()

    class Freshness(_Freshness):
        def __init__(self, *args):
            super().__init__(*args)
            instances.append(self)
            self.watcher.watch = lambda roots: None
            self.watcher.run = forever
            self.volumes.snapshot = lambda: None
            self.volumes.run = forever
            self.guard.free_bytes = lambda: 3_000_000_000

        def _reconcile(self, uuid, only, progress):
            reconciled.set()
            return Reconciled([], 0, 0, 0)

    class Server:
        def __init__(self, path, state):
            self.state = state

        async def start(self):
            pass

        async def stop(self):
            await self.setup.stop()

        async def broadcast(self, message):
            pass

        async def push_status(self, **kwargs):
            pass

    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    monkeypatch.setattr(main, '_Freshness', Freshness)
    monkeypatch.setattr(main, 'IpcServer', Server)
    monkeypatch.setattr(main, '_wait_for_work', wait)
    pending = asyncio.create_task(main._serve(manifest, interval=60))
    try:
        await asyncio.wait_for(waiting.wait(), .5)
        await instances[0].on_dirty({'volume': 'v'}, {tmp_path})
        await asyncio.wait_for(reconciled.wait(), .1)
        manifest.unlink()
        instances[0].wake.set()
        assert await asyncio.wait_for(pending, .5) == 0
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


async def test_volume_event_wakes_loop(freshness):
    event = VolumeEvent('returned', Volume('v', 'fixture', 'exfat', 10,
                                         freshness.directory, True, True))
    waiting = asyncio.create_task(main._wait_for_work(asyncio.Event(), freshness.wake, 60))
    try:
        await asyncio.sleep(0)
        await freshness.on_events([event])
        await asyncio.wait_for(waiting, .1)
        assert freshness.dirty == {'v': None}
    finally:
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)


async def test_dirty_wakeup_keeps_reconcile_backoff(freshness, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(main.time, 'monotonic', lambda: clock[0])
    attempts = []

    def fail(*args):
        attempts.append(clock[0])
        raise sqlite3.DatabaseError('fixture')

    monkeypatch.setattr(freshness, '_reconcile', fail)
    await freshness.on_dirty({'volume': 'v'}, {freshness.directory})
    await freshness.tick()
    clock[0] += .1
    await freshness.on_dirty({'volume': 'v'}, {freshness.directory})
    await freshness.tick()
    assert attempts == [100.0]
    clock[0] = 102.0
    await freshness.tick()
    assert attempts == [100.0, 102.0]


@pytest.mark.parametrize('step', ['watcher', 'disk', 'reconcile', 'status', 'kick'])
@pytest.mark.parametrize('error', [sqlite3.DatabaseError, OSError, subprocess.CalledProcessError])
async def test_freshness_errors_retry_next_tick(freshness, monkeypatch, caplog, step, error):
    attempts = []

    def fail_once():
        attempts.append(step)
        if len(attempts) == 1:
            if error is subprocess.CalledProcessError:
                raise error(1, ['private/path'], output='private text')
            raise error('private/path private text')

    async def async_failure(*args, **kwargs):
        fail_once()

    def reconcile(*args, **kwargs):
        fail_once()
        return Reconciled([], 0, 0, 0)

    if step == 'watcher':
        monkeypatch.setattr(freshness.watcher, 'watch', lambda roots: fail_once())
    elif step == 'disk':
        monkeypatch.setattr(freshness.guard, 'check', fail_once)
    elif step in ('reconcile', 'status'):
        freshness.defer('v', {freshness.directory})
        if step == 'reconcile':
            monkeypatch.setattr(freshness, '_reconcile', reconcile)
        else:
            monkeypatch.setattr(freshness, '_reconcile', lambda *args: Reconciled([], 0, 0, 0))
            monkeypatch.setattr(freshness.server, 'push_status', async_failure)
    else:
        freshness.pending.add('v')
        monkeypatch.setattr(freshness.server.setup, 'kick', async_failure)
    clock = [100.0]
    monkeypatch.setattr(main.time, 'monotonic', lambda: clock[0])
    await freshness.tick()
    clock[0] += 2
    await freshness.tick()
    assert attempts == [step, step]
    assert 'private/path' not in caplog.text and 'private text' not in caplog.text


async def test_failing_reconcile_backs_off_and_success_resets(freshness, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(main.time, 'monotonic', lambda: clock[0])
    attempts = []
    failing = [True]

    def reconcile(*args, **kwargs):
        attempts.append(clock[0])
        if failing[0]:
            raise sqlite3.DatabaseError('database disk image is malformed')
        return Reconciled([], 0, 0, 0)

    monkeypatch.setattr(freshness, '_reconcile', reconcile)
    freshness.defer('v', {freshness.directory})
    for _ in range(200):
        await freshness.tick()
        clock[0] += .5
    gaps = [later - earlier for earlier, later in itertools.pairwise(attempts)]
    assert gaps[:5] == [2, 4, 8, 16, 30]
    assert set(gaps[5:]) <= {30}
    failing[0] = False
    clock[0] += 30
    await freshness.tick()
    assert not freshness.dirty and not freshness.retry
    freshness.defer('v', {freshness.directory})
    await freshness.tick()
    assert not freshness.dirty


@pytest.mark.parametrize('lock_mode', [fcntl.LOCK_EX, fcntl.LOCK_SH])
async def test_reconcile_waits_for_external_writer_and_warm_reader(
        freshness, monkeypatch, lock_mode):
    from omafindd import rules

    root = freshness.directory / 'docs'
    root.mkdir()
    note = root / 'new.txt'
    note.write_text('fixture')
    freshness.settings().roots.append({'path': str(root), 'volume': 'v', 'excludes': []})
    monkeypatch.setattr(rules, 'walk', lambda *args, **kwargs: iter([note]))
    descriptor = os.open(freshness.directory / 'index.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, lock_mode | fcntl.LOCK_NB)
        freshness.defer('v', {root})
        await freshness.tick()
        assert not freshness.known('v')
        assert freshness.dirty == {'v': {root}}
        want = os.open(freshness.directory / 'index.want', os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(want, fcntl.LOCK_SH | fcntl.LOCK_NB)
        finally:
            os.close(want)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        await freshness.tick()
        assert freshness.known('v') and not freshness.dirty
        store = Store.open_existing(freshness.directory / 'index/v.sqlite', freshness.directory)
        try:
            assert store.db.execute('SELECT path FROM files').fetchone()[0] == 'docs/new.txt'
        finally:
            store.close()
    finally:
        os.close(descriptor)


async def test_reconcile_holds_writer_lock_through_walk(freshness, monkeypatch):
    from omafindd import rules

    root = freshness.directory / 'docs'
    root.mkdir()
    freshness.settings().roots.append({'path': str(root), 'volume': 'v'})

    def walk(*args, **kwargs):
        descriptor = os.open(freshness.directory / 'index.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)
        return iter([])

    monkeypatch.setattr(rules, 'walk', walk)
    await freshness.reconcile('v')


async def test_volume_callback_failure_is_retried(freshness, monkeypatch, caplog):
    calls = []

    async def status(**kwargs):
        calls.append('status')
        if len(calls) == 1:
            raise sqlite3.OperationalError('private/path private text')

    monkeypatch.setattr(freshness.server, 'push_status', status)
    event = VolumeEvent('gone', Volume('v', 'fixture', 'exfat', 10, None, True, False))
    await freshness.on_events([event])
    await freshness.tick()
    assert calls == ['status', 'status']
    assert 'private/path' not in caplog.text


async def test_daemon_child_can_take_intent_while_reconcile_is_deferred(freshness):
    descriptor = os.open(freshness.directory / 'index.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        freshness.defer('v', None)
        await freshness.tick()
        assert freshness._reconcile_want is not None
        freshness.server.setup.busy = True
        await freshness.tick()
        assert freshness._reconcile_want is None
        want = os.open(freshness.directory / 'index.want', os.O_RDWR)
        try:
            fcntl.flock(want, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(want)
        assert freshness.dirty == {'v': None}
    finally:
        os.close(descriptor)


async def test_failed_reconcile_notification_keeps_indexing_kick(freshness, monkeypatch):
    from omafindd import rules

    root = freshness.directory / 'docs'
    root.mkdir()
    note = root / 'new.txt'
    note.write_text('fixture')
    freshness.settings().roots.append({'path': str(root), 'volume': 'v'})
    monkeypatch.setattr(rules, 'walk', lambda *args, **kwargs: iter([note]))
    broadcasts, kicks = [], []

    async def broadcast(body):
        broadcasts.append(body)
        if len(broadcasts) == 1:
            raise OSError('private/path private text')

    async def kick(uuid):
        kicks.append(uuid)

    monkeypatch.setattr(freshness.server, 'broadcast', broadcast)
    monkeypatch.setattr(freshness.server.setup, 'kick', kick)
    clock = [100.0]
    monkeypatch.setattr(main.time, 'monotonic', lambda: clock[0])
    await freshness.reconcile('v', announce=True)
    assert freshness.pending == {'v'}
    assert freshness.dirty == {'v': None}
    clock[0] += 2
    await freshness.tick()
    assert kicks == ['v']
    assert not freshness.dirty


def test_setup_progress_reads_existing_wal_database_with_rw_mode(tmp_path, monkeypatch):
    from omafindd.setup import SetupService

    path = tmp_path / 'index/v.sqlite'
    store = Store(path, volume='v', mount=tmp_path, label='fixture')
    store.close()
    connect = sqlite3.connect

    def opened(database, **kwargs):
        if '?mode=ro' in str(database):
            raise sqlite3.DatabaseError('injected stale wal-index')
        return connect(database, **kwargs)

    monkeypatch.setattr(sqlite3, 'connect', opened)
    monkeypatch.setattr('omafindd.setup.mounted_volumes', lambda: {})
    setup = SetupService(data_dir=tmp_path, plugin_root=tmp_path,
                         settings=lambda: SimpleNamespace(roots=[]), broadcast=None, runtime=None)
    assert setup._progress()['volumes'] == {'v': {'label': 'fixture', 'done': 0, 'total': 0}}
