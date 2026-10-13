import asyncio
import fcntl
import os
from types import SimpleNamespace

import pytest
from fakes.embedder import FakeEmbedder
from omafindd import indexing, main
from omafindd.embedder import EmbeddingError
from omafindd.main import _Freshness
from omafindd.service import SearchService
from omafindd.settings import Settings
from omafindd.setup import SetupService
from omafindd.state import State


@pytest.fixture(autouse=True)
def inline_io(monkeypatch):
    async def inline(callback, *args, **kwargs):
        return callback(*args, **kwargs)

    monkeypatch.setattr(asyncio, 'to_thread', inline)


class SharedEmbedder(FakeEmbedder):
    connection_env = {'OMAFIND_EMBED_URL': 'http://127.0.0.1:1234',
                      'OMAFIND_EMBED_KEY': 'fixture-key'}

    def __init__(self):
        super().__init__()
        self.stops = 0

    async def stop(self):
        self.stops += 1
        await super().stop()


class Child:
    pid = 99999999
    returncode = None

    def __init__(self):
        self.finished = asyncio.Event()

    async def wait(self):
        await self.finished.wait()
        return self.returncode

    def finish(self):
        self.returncode = 0
        self.finished.set()


@pytest.fixture
def leased_service(tmp_path):
    return SearchService(tmp_path / 'index', lambda: Settings(),
                         SharedEmbedder(), State(model='ready'))


async def test_idle_timer_does_not_stop_server_during_lease(leased_service):
    service = leased_service
    try:
        env = await service.lease_indexer()
        assert env['OMAFIND_EMBED_URL'] == 'http://127.0.0.1:1234'
        service._arm_idle()
        await service._idle(0)
        assert service.embedder.mode == 'full'
        assert service.embedder.stops == 0
        await service.release_indexer()
        await service._idle(0)
        assert service.embedder.mode is None
    finally:
        await service.stop()


async def test_lease_keeps_queries_warm_and_excludes_external_indexer(leased_service, tmp_path):
    service = leased_service
    try:
        await service.lease_indexer()
        with (tmp_path / 'index.want').open('a') as want, (
                tmp_path / 'index.lock').open('a') as lock:
            with pytest.raises(BlockingIOError):
                fcntl.flock(want, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            await service.yield_to_indexer()
            await service._start('text')
            assert service.embedder.mode == 'full'
            assert service.embedder.stops == 0
    finally:
        await service.release_indexer()
        await service.stop()


async def test_queries_keep_meaning_leg_while_shared_child_holds_lock(
        leased_service, tmp_path, monkeypatch):
    from omafindd import rules
    from omafindd.crawler import crawl
    from omafindd.extractors import Segment
    from omafindd.store import Store

    service = leased_service
    path = tmp_path / 'note.txt'
    path.write_text('lunar eclipse telescope')
    monkeypatch.setattr(rules, 'walk', lambda *args, **kwargs: iter([path]))
    service.current_mounts = lambda: {'v': tmp_path}
    store = Store(tmp_path / 'index/v.sqlite', volume='v', mount=tmp_path)
    try:
        crawl(store, [{'path': str(tmp_path), 'excludes': []}])
        file = store.db.execute('SELECT id FROM files').fetchone()[0]
        vectors = await service.embedder.embed_documents(['lunar eclipse telescope'])
        store.write(file, [Segment('chunk', 'text', 'lunar eclipse telescope')], vectors,
                    state='done', info={})
        await service.lease_indexer()
        with (tmp_path / 'index.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            reply = await service.handle({'t': 'search', 'seq': 1, 'q': 'lunar eclipse'})
        assert reply['legs'] == ['words', 'meaning']
        assert reply['degraded'] is None
        assert reply['items'][0]['name'] == 'note.txt'
        assert service.embedder.stops == 0
    finally:
        store.close()
        await service.release_indexer()
        await service.stop()


@pytest.mark.parametrize('volume', [None, 'v'])
async def test_daemon_incremental_child_gets_url_and_keeps_warm_server(
        leased_service, tmp_path, monkeypatch, volume):
    service = leased_service
    child, calls = Child(), []
    settings = Settings(roots=[{'path': str(tmp_path), 'volume': 'v', 'excludes': []}])

    async def nothing(*args, **kwargs):
        pass

    async def spawn(*argv, **kwargs):
        calls.append((argv, kwargs))
        return child

    server = SimpleNamespace(state=service.state, broadcast=nothing, push_status=nothing)
    freshness = _Freshness(tmp_path, lambda: settings, server, service, {})
    setup = SetupService(data_dir=tmp_path, plugin_root=tmp_path,
                         settings=lambda: settings, broadcast=nothing, runtime=None,
                         spawn=freshness.spawn_indexer)
    server.setup = setup
    monkeypatch.setattr(main.asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setattr(setup, '_progress', lambda: {'t': 'progress'})
    try:
        await setup.kick(volume)
        argv, options = calls[0]
        assert argv[2:4] == ('reindex', '--incremental')
        assert argv[4:] == (() if volume is None else ('--volume', 'v'))
        assert options['env']['OMAFIND_EMBED_URL'] == 'http://127.0.0.1:1234'
        assert options['env']['OMAFIND_EMBED_KEY'] == 'fixture-key'
        await service.yield_to_indexer()
        assert service.embedder.stops == 0
        assert service.index_leased
        child.finish()
        for _ in range(10):
            if not service.index_leased:
                break
            await asyncio.sleep(0)
        assert not service.index_leased
        with (tmp_path / 'index.lock').open('a') as lock:
            # The daemon still owns its warm server until the ordinary idle timeout.
            with pytest.raises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        child.finish()
        await service.stop()


async def test_failed_start_launches_incremental_child_without_url(
        leased_service, tmp_path, monkeypatch):
    service = leased_service
    calls = []

    async def fail(mode):
        raise EmbeddingError('injected start failure')

    async def spawn(*argv, **kwargs):
        calls.append(kwargs.get('env', dict(os.environ)))
        return Child()

    service.embedder.start = fail
    monkeypatch.setenv('OMAFIND_EMBED_URL', 'http://127.0.0.1:9999')
    monkeypatch.setenv('OMAFIND_EMBED_KEY', 'stale-fixture-key')
    monkeypatch.setattr(main.asyncio, 'create_subprocess_exec', spawn)
    freshness = _Freshness(tmp_path, lambda: Settings(), None, service, {})
    try:
        await freshness.spawn_indexer('python', 'omafind', 'reindex', '--incremental')
        inherited_url = 'OMAFIND_EMBED_URL' in calls[0]
        inherited_key = 'OMAFIND_EMBED_KEY' in calls[0]
        assert inherited_url is False
        assert inherited_key is False
        assert not service.index_leased
        with (tmp_path / 'index.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        await service.stop()


async def test_shared_child_indexes_under_daemon_lock(leased_service, tmp_path, monkeypatch):
    service = leased_service
    monkeypatch.setattr(indexing, 'mounted_volumes', lambda: {})
    try:
        await service.lease_indexer()
        adapter = SimpleNamespace(shared=True, stop=service.release_indexer)
        await indexing.reindex([], directory=tmp_path, embedder=adapter)
        assert service.embedder.stops == 0
    finally:
        await service.release_indexer()
        await service.stop()


async def test_reconcile_retains_warm_server_until_child_launch(
        leased_service, tmp_path, monkeypatch):
    from omafindd import rules

    service = leased_service
    root = tmp_path / 'docs'
    root.mkdir()
    note = root / 'new.txt'
    note.write_text('fixture')
    settings = Settings(roots=[{'path': str(root), 'volume': 'v', 'excludes': []}])

    async def nothing(*args, **kwargs):
        pass

    server = SimpleNamespace(setup=SimpleNamespace(busy=False, _index_lock=asyncio.Lock()),
                             broadcast=nothing, push_status=nothing)
    service.current_mounts = lambda: {'v': tmp_path}
    monkeypatch.setattr(rules, 'walk', lambda *args, **kwargs: iter([note]))
    freshness = _Freshness(tmp_path, lambda: settings, server, service, {})
    try:
        await service._start('full')
        await freshness.reconcile('v', {root})
        assert freshness.pending == {'v'}
        assert not freshness.dirty
        assert service.index_leased
        assert service.embedder.stops == 0
    finally:
        await service.release_indexer()
        await service.stop()


async def test_lazy_daemon_warms_indexer_mode(monkeypatch):
    embedder = SharedEmbedder()
    monkeypatch.setattr(main, 'Embedder', lambda **kwargs: embedder)
    monkeypatch.setattr(main, 'Adapter', lambda value: value)
    lazy = main._LazyEmbedder()
    await lazy.start('text')
    assert lazy.mode == 'full'
    await lazy.stop()


async def test_release_without_a_lease_does_not_extend_idle_timeout(leased_service, monkeypatch):
    service = leased_service
    sleeping, expire = asyncio.Event(), asyncio.Event()
    sleeps = []
    sleep = asyncio.sleep

    async def timer(seconds):
        if seconds:
            sleeps.append(seconds)
            sleeping.set()
            await expire.wait()
        else:
            await sleep(0)

    monkeypatch.setattr(asyncio, 'sleep', timer)
    try:
        await service._start('full')
        service._arm_idle()
        await sleeping.wait()
        await service.release_indexer()
        await sleep(0)
        assert len(sleeps) == 1
        expire.set()
        for _ in range(10):
            await sleep(0)
        assert service.embedder.mode is None
    finally:
        expire.set()
        await service.stop()


async def test_previous_child_exit_cannot_release_next_child_lease(leased_service):
    service = leased_service
    first, second = Child(), Child()
    try:
        await service.lease_indexer()
        service.watch_indexer(first)
        first_task = service._lease_task
        async with service._lock:
            first.finish()
            await asyncio.sleep(0)
            service.watch_indexer(second)
        await first_task
        assert service.index_leased
        assert service.embedder.stops == 0
    finally:
        first.finish()
        second.finish()
        await service.stop()


async def test_reconcile_can_retain_lease_before_previous_exit_monitor_runs(leased_service):
    service = leased_service
    first = Child()
    try:
        await service.lease_indexer()
        service.watch_indexer(first)
        first_task = service._lease_task
        first.finish()
        await service.lease_indexer()
        await first_task
        assert service.index_leased
        assert service.embedder.stops == 0
    finally:
        first.finish()
        await service.release_indexer()
        await service.stop()
