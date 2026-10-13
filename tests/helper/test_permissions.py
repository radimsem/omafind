import json
import stat

from test_cli import FakeRun
from test_cli import cli as cli_fixture
from test_cli import env as env_fixture
from test_cli import venv as venv_fixture

cli = cli_fixture
env = env_fixture
venv = venv_fixture


def test_0644_db_listed_in_status_json(cli, env, venv, capsys):
    from pathlib import Path

    data = Path(env['XDG_DATA_HOME']) / 'omafind'
    index = data / 'index'
    index.mkdir(parents=True, mode=0o700)
    data.chmod(0o700)
    db = index / 'u.sqlite'
    db.touch(mode=0o644)
    db.chmod(0o644)
    assert cli.main(['status', '--json'], env, run=FakeRun(),
                    probe=lambda path, timeout: True) == 0
    assert json.loads(capsys.readouterr().out)['permissions'] == [
        {'path': str(db), 'expected': '0600', 'actual': '0644'}]
    assert stat.S_IMODE(db.stat().st_mode) == 0o644


def test_permissions_cover_private_paths_without_recursing(tmp_path):
    from omafindd import permissions

    data = tmp_path / 'data'
    runtime = tmp_path / 'run'
    dirs = [data, data / 'index', data / 'thumbs', data / 'thumbs/u',
            data / 'model', data / 'cache', data / 'runtime', data / 'venv',
            runtime, runtime / 'preview']
    files = [data / 'index/u.sqlite', data / 'index/u.sqlite-wal',
             data / 'index/u.sqlite-shm', data / 'index/u.sqlite.bad',
             data / 'index/run.json', data / 'index/reindex.log',
             data / 'index/health.json', data / 'thumbs/u/1.jpg',
             data / 'model/m.gguf', data / 'model/m.gguf.part',
             data / 'journal', data / 'running', data / 'index.lock',
             data / 'index.want', runtime / 'ui.sock']
    for path in dirs:
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o755)
    for path in files:
        path.touch()
        path.chmod(0o644)
    for name in ('venv', 'runtime', 'cache'):
        (data / name / 'public').touch(mode=0o644)
    found = permissions.check(data, runtime)
    assert {item['path'] for item in found} == {str(path) for path in dirs + files}
    for path in dirs:
        path.chmod(0o700)
    for path in files:
        path.chmod(0o600)
    assert permissions.check(data, runtime) == []
    assert permissions.check(tmp_path / 'missing', None) == []


def test_fix_dirs_is_shallow_and_does_not_follow_symlinks(tmp_path):
    from omafindd import permissions

    data = tmp_path / 'data'
    nested = data / 'runtime/bin'
    nested.mkdir(parents=True)
    external = tmp_path / 'external'
    external.mkdir(mode=0o755)
    (data / 'link').symlink_to(external, target_is_directory=True)
    for path in (data, nested.parent, nested):
        path.chmod(0o755)
    permissions.fix_dirs(data)
    assert stat.S_IMODE(data.stat().st_mode) == 0o700
    assert stat.S_IMODE(nested.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(nested.stat().st_mode) == 0o755
    assert stat.S_IMODE(external.stat().st_mode) == 0o755
    assert {'path': str(data / 'link'), 'expected': '0700', 'actual': '0777'} in (
        permissions.check(data, None))


def test_bad_model_digest_makes_search_words_only(tmp_path, monkeypatch):
    from omafindd import models, paths
    from omafindd.state import State

    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    paths.model_dir().mkdir(parents=True)
    files = tuple(models.ModelFile(name, 4, '0' * 64) for name in (
        'embeddinggemma-2-Q8_0.gguf', 'mmproj-embeddinggemma-2-Q8_0.gguf'))
    for file in files:
        (paths.model_dir() / file.name).write_bytes(b'bad!')
    verifier = models.Verifier(paths.model_dir(), files=files)
    state = State.detect(verifier=verifier)
    assert state.model == 'missing'

    import asyncio
    from pathlib import Path

    from omafindd.service import SearchService
    from omafindd.settings import Settings
    from omafindd.store import Store
    from test_ipc_volumes import Embedder

    directory = tmp_path / 'index'
    store = Store(directory / 'u.sqlite', volume='u', mount=tmp_path)
    store.db.execute("INSERT INTO files(path,kind,size,mtime,inode,device) "
                     "VALUES('note.txt','text',4,1,1,1)")
    store.name_row(1, 'note.txt')
    store.db.commit()
    store.close()

    async def search():
        service = SearchService(directory, lambda: Settings(), Embedder(), state,
                                mounts_resolver=lambda: {'u': tmp_path},
                                volume_resolver=lambda path, **kw: ('u', Path(tmp_path)))
        try:
            reply = await service.handle({'t': 'search', 'seq': 1, 'q': 'note'})
            assert reply['legs'] == ['words']
            assert reply['degraded'] == 'embedding model failed verification'
            assert reply['items'][0]['name'] == 'note.txt'
        finally:
            await service.stop()

    asyncio.run(search())


def test_health_roundtrip_is_private_and_bad_data_is_empty(tmp_path):
    from omafindd import health

    path = tmp_path / 'index/health.json'
    assert health.read(path) == {}
    data = {'model': {'verified': False}, 'recovery': {'mode': 'reconcile'}}
    health.write(path, data)
    assert health.read(path) == data
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(path.parent.iterdir()) == [path]
    for bad in ('{', '[]', 'null'):
        path.write_text(bad)
        assert health.read(path) == {}


def test_unreadable_directory_does_not_change_status_exit_code(cli, env, venv, capsys,
                                                               monkeypatch):
    from pathlib import Path

    data = Path(env['XDG_DATA_HOME']) / 'omafind'
    data.mkdir(parents=True)
    data.chmod(0o755)
    original = Path.iterdir

    def denied(path):
        if path == data:
            raise PermissionError('cannot list data directory')
        return original(path)

    monkeypatch.setattr(Path, 'iterdir', denied)
    assert cli.main(['status', '--json'], env, run=FakeRun(),
                    probe=lambda path, timeout: True) == 0
    assert {'path': str(data), 'expected': '0700', 'actual': '0755'} in (
        json.loads(capsys.readouterr().out)['permissions'])


def test_verified_models_are_ready_only_while_both_files_exist(tmp_path, monkeypatch):
    import hashlib

    from omafindd import models, paths
    from omafindd.state import State

    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    directory = paths.model_dir()
    directory.mkdir(parents=True)
    files = tuple(models.ModelFile(name, 4, hashlib.sha256(b'good').hexdigest()) for name in (
        'embeddinggemma-2-Q8_0.gguf', 'mmproj-embeddinggemma-2-Q8_0.gguf'))
    for file in files:
        (directory / file.name).write_bytes(b'good')
    verifier = models.Verifier(directory, files=files)
    assert State.detect(verifier).model == 'ready'
    (directory / files[0].name).unlink()
    assert State.detect(verifier).model == 'missing'


def test_unreadable_runtime_and_model_paths_do_not_change_status_code(
        cli, env, venv, capsys, monkeypatch):
    from pathlib import Path

    is_file = Path.is_file

    def denied(path):
        if path.is_relative_to(venv):
            return is_file(path)
        raise PermissionError('cannot inspect file')

    monkeypatch.setattr(Path, 'is_file', denied)
    assert cli.main(['status', '--json'], env, run=FakeRun(),
                    probe=lambda path, timeout: True) == 0
    details = json.loads(capsys.readouterr().out)
    assert details['runtime']['present'] is False
    assert details['model']['files'] == dict.fromkeys((
        'embeddinggemma-2-Q8_0.gguf', 'mmproj-embeddinggemma-2-Q8_0.gguf'), False)
