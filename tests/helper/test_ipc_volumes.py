import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from omafindd import errors
from omafindd.ipc import IpcServer
from omafindd.service import SearchService
from omafindd.settings import Settings
from omafindd.state import State
from omafindd.store import Store
from test_ipc import HELLO, memory_client, memory_reply


@pytest.fixture(autouse=True)
def inline_threads(monkeypatch):
    async def inline(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr(asyncio, 'to_thread', inline)


class Embedder:
    mode = None

    async def stop(self):
        pass

    async def start(self, mode):
        raise AssertionError('words-only search must not start the embedder')


def seeded(directory, mount, *, volume='usb', label='Photos2024'):
    store = Store(directory / f'{volume}.sqlite', volume=volume, mount=mount, label=label)
    store.db.execute("INSERT INTO files(path,kind,size,mtime,inode,device,state,indexed_at) "
                     "VALUES('docs/note.txt','text',4,1,1,1,'done',1)")
    store.name_row(1, 'docs/note.txt')
    store.db.commit()
    store.close()


@pytest.mark.parametrize('online', [False, True])
@pytest.mark.parametrize('volume,label,drive', [
    ('usb', 'Photos2024', True), ('usb', 'root', True),
    ('internal', 'root', False), ('internal', 'Home', False),
])
async def test_result_drive_metadata_uses_home_volume_identity(
        tmp_path, monkeypatch, online, volume, label, drive):
    from omafindd import store

    directory = tmp_path / 'index'
    old_mount, mount = Path('/media/Photos2024'), Path('/media/new')
    seeded(directory, old_mount, volume=volume, label=label)
    monkeypatch.setattr(store, 'volume_for', lambda path, **kw: ('internal', tmp_path))
    service = SearchService(directory, lambda: Settings(), Embedder(), State(model='ready'),
                            mounts_resolver=lambda: {volume: mount} if online else {},
                            volume_resolver=lambda path, **kw: ('internal', tmp_path))
    try:
        reply = await service.handle({'t': 'search', 'seq': 1, 'q': 'note', 'legs': ['words']})
        item = reply['items'][0]
        assert item['drive'] is drive
        assert item['label'] == label
        assert item['offline'] is (not online and drive)
        parent = (mount if online else old_mount) / 'docs' if drive else tmp_path / 'docs'
        assert item['path'] == str(parent / 'note.txt')
        assert item['dir'] == ('/docs' if drive else str(parent))
    finally:
        await service.stop()


async def test_offline_items_carry_offline_and_label(tmp_path):
    directory = tmp_path / 'index'
    seeded(directory, Path('/media/Photos2024'))
    service = SearchService(directory, lambda: Settings(), Embedder(), State(),
                            mounts_resolver=lambda: {},
                            volume_resolver=lambda path, **kw: ('internal', tmp_path))
    try:
        reply = await service.handle({'t': 'search', 'seq': 1, 'q': 'note', 'legs': ['words']})
        item = reply['items'][0]
        assert item['offline'] is True
        assert item['label'] == 'Photos2024'
        assert item['path'] == '/media/Photos2024/docs/note.txt'
        assert item['dir'] == '/docs'
        service.mounts_resolver = lambda: {'usb': Path('/media/new')}
        service._mountinfo = None
        online = await service.handle({'t': 'search', 'seq': 2, 'q': 'note', 'legs': ['words']})
        assert online['items'][0]['offline'] is False
        assert online['items'][0]['path'] == '/media/new/docs/note.txt'
    finally:
        await service.stop()


def test_status_offline_lists_label(tmp_path):
    directory = tmp_path / 'index'
    seeded(directory, Path('/media/Photos2024'))
    service = SimpleNamespace(directory=directory, settings=lambda: Settings(),
                              mounts_resolver=lambda: {})
    server = IpcServer(tmp_path / 'ui.sock', State(), service=service)
    assert server.status_message()['offline'] == ['Photos2024']
    service.mounts_resolver = lambda: {'usb': Path('/media/new')}
    assert server.status_message()['offline'] == []


async def test_volume_and_paused_replayed_after_hello(tmp_path):
    server = IpcServer(tmp_path / 'ui.sock', State(), peer_uid=lambda _: __import__('os').getuid())
    volume = {'t': 'volume', 'uuid': 'usb', 'label': 'Photos2024', 'fs': 'exfat',
              'size': 123, 'mount': '/media/Photos2024', 'online': True, 'known': False}
    paused = {'t': 'paused', 'error': errors.disk_low().to_dict(), 'free_gb': 1.4, 'need_gb': 2}
    server.replay = lambda: [volume, paused]
    reader, writer = memory_client(server)
    try:
        reader.feed_data(HELLO)
        assert await memory_reply(writer) == server.state.message()
        assert await memory_reply(writer) == volume
        assert await memory_reply(writer) == paused
    finally:
        reader.feed_eof()
        await server.stop()


async def test_status_pushes_when_indexed_count_grows(tmp_path):
    directory = tmp_path / 'index'
    seeded(directory, Path('/media/Photos2024'))
    server = IpcServer(tmp_path / 'ui.sock', State(), service=SimpleNamespace(
        directory=directory, settings=lambda: Settings(), mounts_resolver=lambda: {}))
    pushes = []

    async def broadcast(body):
        pushes.append(body)

    server.broadcast = broadcast
    await server.push_status(now=0)
    store = Store(directory / 'usb.sqlite', volume='usb', mount=Path('/media/Photos2024'),
                  label='Photos2024')
    store.db.execute("INSERT INTO files(path,kind,size,mtime,inode,device,indexed_at) "
                     "VALUES('new.txt','text',4,1,2,1,2)")
    store.db.commit()
    store.close()
    await server.push_status(now=0.5)
    assert [body['files'] for body in pushes] == [1, 2]


def test_daemon_import_is_light():
    import subprocess
    import sys

    result = subprocess.run([sys.executable, '-c',
                             'import omafindd.main, sys; '
                             'assert "numpy" not in sys.modules; '
                             'assert "torch" not in sys.modules'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.fixture
def freshness(tmp_path, monkeypatch):
    from omafindd.main import _Freshness

    directory = tmp_path / 'data'
    directory.mkdir()
    settings = Settings()
    server = IpcServer(tmp_path / 'ui.sock', State(model='ready'))
    server.setup = SimpleNamespace(busy=False, ignored=set(), kicks=[], _index_lock=asyncio.Lock())

    async def kick(volume=None):
        server.setup.kicks.append(volume)

    server.setup.kick = kick
    async def nothing():
        pass

    service = SimpleNamespace(current_mounts=lambda: {'u': tmp_path}, _mountinfo=None,
                              index_leased=False, lease_indexer=nothing, release_indexer=nothing)
    result = _Freshness(directory, lambda: settings, server, service, {})
    result.test_settings = settings
    result.test_pushes = []

    async def broadcast(body):
        result.test_pushes.append(body)

    server.broadcast = broadcast
    monkeypatch.setattr(result.watcher, 'watch', lambda roots: None)
    monkeypatch.setattr(result.guard, 'free_bytes', lambda: 3_000_000_000)
    return result


async def test_watcher_dirty_defers_until_child_exit_and_kicks(freshness, tmp_path):
    from omafindd import rules

    docs = tmp_path / 'docs'
    docs.mkdir()
    note = docs / 'new-note.txt'
    note.write_text('local fixture')
    root = {'path': str(docs), 'volume': 'u', 'excludes': []}
    freshness.test_settings.roots.append(root)
    freshness.service.settings = lambda: freshness.test_settings
    freshness.service.directory = freshness.directory / 'index'
    freshness.server.service = freshness.service
    freshness.service.mounts_resolver = freshness.service.current_mounts
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(rules, 'walk', lambda *args, **kwargs: iter([note]))
        freshness.server.setup.busy = True
        await freshness.on_dirty(root, {docs})
        await freshness.tick()
        assert not freshness.known('u')
        assert not freshness.server.setup.kicks
        freshness.server.setup.busy = False
        await freshness.tick()
    assert freshness.server.setup.kicks == ['u']
    store = Store.open_existing(freshness.directory / 'index/u.sqlite', tmp_path)
    try:
        assert store.db.execute('SELECT path,state FROM files').fetchone()[:] == (
            'docs/new-note.txt', 'pending')
    finally:
        store.close()


async def test_hello_replay_skips_known_and_ignored_volumes(freshness):
    from omafindd.volumes import Volume

    freshness.volumes._last = {
        uuid: Volume(uuid, uuid, 'exfat', 123, Path('/media') / uuid, True, True)
        for uuid in ('known', 'ignored', 'fresh')}
    freshness.directory.joinpath('index').mkdir()
    freshness.directory.joinpath('index/known.sqlite').touch()
    freshness.server.setup.ignored.add('ignored')
    assert [event['uuid'] for event in freshness.replay()] == ['fresh']


async def test_disk_transitions_are_broadcast_and_replayed(freshness, monkeypatch):
    monkeypatch.setattr(freshness.guard, 'free_bytes', lambda: 1_400_000_000)
    await freshness.check_disk()
    await freshness.check_disk()
    assert freshness.test_pushes == [
        {'t': 'paused', 'error': errors.disk_low().to_dict(), 'free_gb': 1.4, 'need_gb': 2}]
    assert freshness.replay() == freshness.test_pushes
    monkeypatch.setattr(freshness.guard, 'free_bytes', lambda: 2_100_000_000)
    await freshness.check_disk()
    assert freshness.test_pushes[-1] == {'t': 'resumed'}
    assert freshness.replay() == []


async def test_returned_drive_preserves_label_and_remaps_before_meta_advances(
        freshness, tmp_path, monkeypatch):
    from omafindd import health, paths, rules
    from omafindd.settings import SettingsReader
    from omafindd.volumes import Volume

    monkeypatch.setattr(paths, 'health_path', lambda: freshness.directory / 'index/health.json')
    monkeypatch.setattr('omafindd.main.is_drive', lambda fact: fact.removable)
    old = tmp_path / 'old'
    mount = tmp_path / 'new'
    docs = mount / 'docs'
    docs.mkdir(parents=True)
    note = docs / 'note.txt'
    note.touch()
    seeded(freshness.directory / 'index', old)
    shell = tmp_path / 'shell.json'
    shell.write_text(__import__('json').dumps({'plugins': [{
        'id': 'radimsem.omafind', 'roots': [
            {'path': str(old / 'docs'), 'volume': 'usb', 'excludes': []}]}]}))
    freshness.settings = SettingsReader(shell).read
    freshness.service.current_mounts = lambda: {'usb': mount}
    freshness.volumes._last['usb'] = Volume('usb', 'Photos2024', 'exfat', 123, mount, True, True)
    monkeypatch.setattr(rules, 'walk', lambda *args, **kw: iter([note]))
    await freshness.reconcile('usb', announce=True)
    store = Store.open_existing(freshness.directory / 'index/usb.sqlite', mount)
    try:
        assert store.last_mount == mount
        assert store.label == 'Photos2024'
        assert store.db.execute('SELECT path FROM files').fetchone()[0] == 'docs/note.txt'
    finally:
        store.close()
    assert SettingsReader(shell).read().roots[0]['path'] == str(docs)
    assert health.read(paths.health_path())['mounts']['usb']['previous'] == [str(old)]
    assert freshness.test_pushes[-2]['t'] == 'reconcile'
    assert freshness.test_pushes[-2]['done'] == freshness.test_pushes[-2]['total']


def test_startup_integrity_check_quarantines_and_records_problem(tmp_path, monkeypatch):
    from omafindd.main import _repair

    directory = tmp_path / 'data'
    index = directory / 'index'
    index.mkdir(parents=True)
    (index / 'usb.sqlite').write_text('corrupt database')
    monkeypatch.setattr('omafindd.store.mounted_volumes', lambda: {'usb': Path('/media/drive')})
    problems = _repair(directory)
    assert len(problems) == 1
    assert problems[0]['volume'] == 'usb'
    assert problems[0]['action'] == 'rebuilt'
    assert Path(problems[0]['moved_to']).read_text() == 'corrupt database'
    store = Store.open_existing(index / 'usb.sqlite', Path('/media/drive'))
    assert store.db.execute('SELECT count(*) FROM files').fetchone()[0] == 0
    store.close()


def test_startup_deletes_a_leftover_code_index(tmp_path):
    from omafindd.main import _drop_code_index

    index = tmp_path / 'data/index'
    index.mkdir(parents=True)
    for name in ('code.sqlite', 'code.sqlite-wal', 'code.sqlite-shm', 'usb.sqlite'):
        (index / name).write_text(name)
    _drop_code_index(tmp_path / 'data')
    assert sorted(path.name for path in index.iterdir()) == ['usb.sqlite']
    _drop_code_index(tmp_path / 'data')
    _drop_code_index(tmp_path / 'missing')


async def test_startup_reuses_verifier_and_cleans_marker_on_normal_exit(tmp_path, monkeypatch):
    from omafindd import health, main, paths

    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path))
    monkeypatch.setenv('HOME', str(tmp_path))
    manifest = tmp_path / 'manifest.json'
    manifest.touch()
    data = paths.data_dir()
    (data / 'running').touch()
    calls = []

    class Verifier:
        def __init__(self):
            calls.append('verifier')

        def check(self):
            return False

        def files_report(self):
            return {}

    class Server(IpcServer):
        async def start(self):
            calls.append('start')

    class Freshness:
        spawn_indexer = main._Freshness.spawn_indexer

        def __init__(self, directory, settings, server, service, report):
            self.wake = asyncio.Event()
            self.guard = SimpleNamespace(paused=False)
            self.watcher = SimpleNamespace(run=self.wait, stop=lambda: None)
            self.volumes = SimpleNamespace(snapshot=lambda: None, run=lambda cb: self.wait(),
                                           online=lambda: {})
            self.on_events = None
            self.pending = set()

        async def wait(self):
            await asyncio.Event().wait()

        def replay(self):
            return []

        def known(self, uuid):
            return False

        def defer(self, uuid, only):
            calls.append(('defer', uuid))

        async def check_disk(self):
            pass

        async def tick(self):
            calls.append('tick')
            manifest.unlink()

    monkeypatch.setattr(main, 'Verifier', Verifier)
    monkeypatch.setattr(main, 'IpcServer', Server)
    monkeypatch.setattr(main, '_Freshness', Freshness)
    assert await main._serve(manifest, interval=0.001) == 0
    assert calls == ['verifier', 'start', 'tick']
    report = health.read(data / 'index/health.json')
    assert report['recovery'] == {'clean': False, 'mode': 'reconcile', 'journal_retried': 0}
    assert report['model'] == {'verified': False, 'files': {}}
    assert not (data / 'running').exists()


async def test_unverified_meaning_only_search_returns_words(tmp_path):
    directory = tmp_path / 'index'
    seeded(directory, Path('/media/drive'))
    service = SearchService(directory, lambda: Settings(), Embedder(), State(),
                            mounts_resolver=lambda: {},
                            volume_resolver=lambda path, **kw: ('internal', tmp_path))
    try:
        result = await service.handle({'t': 'search', 'seq': 1, 'q': 'note',
                                       'legs': ['meaning']})
        assert result['legs'] == ['words']
        assert result['degraded'] == errors.embedding_unavailable(
            'embedding model failed verification').to_dict()
        assert result['items'][0]['name'] == 'note.txt'
    finally:
        await service.stop()
