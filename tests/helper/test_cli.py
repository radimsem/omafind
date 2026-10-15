import errno
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODEL_NAMES = ("embeddinggemma-2-Q8_0.gguf", "mmproj-embeddinggemma-2-Q8_0.gguf")


@pytest.fixture
def cli():
    loader = importlib.machinery.SourceFileLoader("omafind_cli", str(ROOT / "bin/omafind"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def env(tmp_path, monkeypatch):
    values = {"HOME": str(tmp_path / "home"), "XDG_CONFIG_HOME": str(tmp_path / "config"),
              "XDG_DATA_HOME": str(tmp_path / "data"), "XDG_RUNTIME_DIR": str(tmp_path / "run")}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return dict(os.environ)


@pytest.fixture
def venv(env):
    python = Path(env["HOME"]) / ".local/share/omafind/venv/bin/python"
    python.parent.mkdir(parents=True)
    python.touch()
    return python.parent.parent


class FakeRun:
    def __init__(self, enabled="enabled", active="active"):
        self.enabled = enabled
        self.active = active
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if command == ["fd", "--version"]:
            return subprocess.CompletedProcess(command, 0, "fd 10.5.0\n", "")
        if command[0] == "uv":
            Path(kwargs["env"]["UV_PROJECT_ENVIRONMENT"]).mkdir(parents=True, exist_ok=True)
        verb = command[2] if len(command) > 2 else ""
        state = {"is-enabled": self.enabled, "is-active": self.active}.get(verb, "")
        code = int(state not in ("", "enabled", "enabled-runtime", "active"))
        return subprocess.CompletedProcess(command, code, state + "\n", "")


@pytest.mark.parametrize("enabled,active,answers,code", [
    ("not-found", "inactive", False, 1),
    ("disabled", "active", True, 1),
    ("enabled", "inactive", False, 2),
    ("enabled", "failed", False, 2),
    ("enabled", "active", False, 3),
    ("enabled", "active", True, 0),
    ("enabled-runtime", "active", True, 0),
])
def test_status_exit_codes_and_json(cli, env, venv, capsys, enabled, active, answers, code):
    run = FakeRun(enabled, active)
    assert cli.main(["status", "--json"], env, run=run,
                    probe=lambda path, timeout: answers) == code
    assert json.loads(capsys.readouterr().out) == {
        "unit": {"enabled": enabled in ("enabled", "enabled-runtime"),
                 "active": active == "active"},
        "socket": {"path": str(Path(env["XDG_RUNTIME_DIR"]) / "omafind/ui.sock"),
                   "answers": answers},
        "tools": {"missing": []},
        "venv": {"path": str(venv), "state": "ready"},
        "runtime": {"path": str(Path(env["XDG_DATA_HOME"]) / "omafind/runtime/bin/llama-server"),
                    "present": False},
        "model": {"path": str(Path(env["XDG_DATA_HOME"]) / "omafind/model"),
                  "files": dict.fromkeys(MODEL_NAMES, False), "verified": False},
        "volumes": [], "queue": 0, "permissions": [], "problems": [], "recovery": {},
    }


def test_setup_twice_installs_unit_and_restarts_active_service(cli, env, capsys):
    run = FakeRun(active="inactive")
    unit = Path(env["XDG_CONFIG_HOME"]) / "systemd/user/omafind.service"
    for active in ("inactive", "active"):
        run.active = active
        run.calls.clear()
        assert cli.main(["setup"], env, run=run, probe=lambda path, timeout: True) == 0
        expected = [
            ["fd", "--version"],
            ["systemctl", "--user", "show-environment"],
            ["uv", "sync", "--project", str(ROOT / "helper"), "--frozen", "--no-dev"],
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "is-active", "omafind.service"],
            ["systemctl", "--user", "enable", "--now", "omafind.service"],
        ]
        if active == "active":
            expected.append(["systemctl", "--user", "restart", "omafind.service"])
        assert [command for command, _ in run.calls] == expected
        assert run.calls[2][1]["env"]["UV_PROJECT_ENVIRONMENT"] == str(
            Path(env["HOME"]) / ".local/share/omafind/venv")
        assert unit.read_text() == (ROOT / "systemd/omafind.service").read_text()
        assert unit.stat().st_mode & 0o777 == 0o644
        assert (Path(env["XDG_DATA_HOME"]) / "omafind").stat().st_mode & 0o777 == 0o700
        output = capsys.readouterr().out
        assert "runtime missing\n" in output
        assert "model missing\n" in output
        assert "bin/omafind build-runtime" in output


@pytest.fixture
def hello_server(cli, env):
    import socket

    path = Path(env["XDG_RUNTIME_DIR"]) / "omafind/ui.sock"
    path.parent.mkdir(parents=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(path))
    except OSError as error:
        server.close()
        if error.errno in (errno.EPERM, errno.EACCES):
            pytest.skip(f"Unix socket bind is blocked: {error}")
        raise
    server.listen()
    server.settimeout(2)
    requests = []
    errors = []

    def answer():
        try:
            with server.accept()[0] as client:
                client.settimeout(2)
                with client.makefile("rb") as stream:
                    requests.append(json.loads(stream.readline()))
                client.sendall(b'{"t":"state","v":1,"runtime":"missing",')
                client.sendall(b'"model":"missing","embedder":"stopped"}\n')
        except (OSError, ValueError, UnicodeError) as error:
            errors.append(error)

    thread = threading.Thread(target=answer)
    thread.start()
    try:
        yield requests
    finally:
        thread.join(timeout=3)
        server.close()
        assert not thread.is_alive()
        assert not errors


def test_setup_waits_for_real_hello_reply(cli, env, hello_server):
    assert cli.main(["setup"], env, run=FakeRun(active="inactive")) == 0
    assert hello_server == [{"t": "hello", "v": 1}]


@pytest.mark.parametrize("valid", [True, False])
def test_build_runtime_builds_before_download_and_digest_check(
        cli, env, monkeypatch, capsys, valid):
    from omafindd import models

    monkeypatch.chdir(Path(env["HOME"]).parent)
    python = Path(env["HOME"]) / ".local/share/omafind/venv/bin/python"
    python.parent.mkdir(parents=True)
    python.touch()
    events = []

    def download(directory, *, progress):
        events.append(("download", directory))
        progress("tiny.gguf", 5, 10)

    def verify(directory):
        events.append(("verify", directory))
        return {"tiny.gguf": valid}

    def run(command, **kwargs):
        assert command == [str(ROOT / "scripts/build-runtime.sh")]
        events.append(("build", kwargs["env"]["OMAFIND_DATA_DIR"]))
        return subprocess.CompletedProcess(command, 0)

    def execve(path, command, environment):
        assert path == str(python)
        assert command[:2] == [str(python), "-c"]
        assert environment == env
        assert Path.cwd() == ROOT / "helper"
        exec(command[2], {"__name__": "__main__"})  # noqa: S102
        raise SystemExit(0)

    monkeypatch.setattr(models, "download", download)
    monkeypatch.setattr(models, "verify", verify)
    with pytest.raises(SystemExit) as result:
        cli.main(["build-runtime"], env, run=run, execve=execve)
    assert result.value.code == (0 if valid else 1)
    data = Path(env["XDG_DATA_HOME"]) / "omafind"
    assert events == [
        ("build", str(data)), ("download", data / "model"), ("verify", data / "model")]
    output = capsys.readouterr()
    assert "model tiny.gguf 5/10 bytes" in output.out
    if not valid:
        assert "model invalid tiny.gguf" in output.err


def test_status_reports_runtime_and_each_model_presence(cli, env, venv, capsys):
    from omafindd import models, paths

    assert set(MODEL_NAMES) == {file.name for file in models.FILES}
    binary = paths.runtime_bin()
    binary.parent.mkdir(parents=True)
    binary.write_text("fake runtime")
    binary.chmod(0o755)
    directory = paths.model_dir()
    directory.mkdir()
    (directory / MODEL_NAMES[0]).touch()
    assert cli.main(["status"], env, run=FakeRun(), probe=lambda path, timeout: True) == 0
    assert capsys.readouterr().out.splitlines()[:7] == [
        "unit enabled", "unit active", "socket answering", "runtime ready", "model missing",
        f"model {MODEL_NAMES[0]} ready", f"model {MODEL_NAMES[1]} missing",
    ]
    assert cli.main(["status", "--json"], env, run=FakeRun(), probe=lambda path, timeout: True) == 0
    details = json.loads(capsys.readouterr().out)
    assert details["runtime"]["present"] is True
    assert details["model"]["files"] == {MODEL_NAMES[0]: True, MODEL_NAMES[1]: False}


@pytest.mark.parametrize("chunks,answers", [
    ([b'bad json\n[]\n{"t":"state",', b'"v":1}\n'], True),
    ([b'{"t":"state","v":1}'], False),
    ([b'{"t":"state","v":2}\n'], False),
    ([b'{"t":"state","v":true}\n'], False),
    ([b"x" * 1_048_577], False),
    ([], False),
])
def test_status_hello_framing(cli, env, venv, monkeypatch, chunks, answers, capsys):
    sent = []
    received = iter(chunks)

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def settimeout(self, timeout):
            assert 0 < timeout <= 0.2

        def connect(self, path):
            assert path == str(Path(env["XDG_RUNTIME_DIR"]) / "omafind/ui.sock")

        def sendall(self, data):
            sent.append(data)

        def recv(self, size):
            return next(received, b"")

    monkeypatch.setattr(cli.socket, "socket", lambda *args: Client())
    assert cli.main(["status", "--json"], env, run=FakeRun()) == (0 if answers else 3)
    assert json.loads(capsys.readouterr().out)["socket"]["answers"] is answers
    assert sent == [b'{"t":"hello","v":1}\n']


def test_setup_stops_on_sync_failure(cli, env, capsys):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command == ["fd", "--version"]:
            return subprocess.CompletedProcess(command, 0, "fd 10.5.0\n", "")
        return subprocess.CompletedProcess(command, int(command[0] == "uv"), "", "sync failed")

    assert cli.main(["setup"], env, run=run) == 1
    assert len(calls) == 3
    assert "sync failed" in capsys.readouterr().err
    assert not (Path(env["XDG_CONFIG_HOME"]) / "systemd/user/omafind.service").exists()


def test_setup_socket_timeout_reports_journal(cli, env, capsys):
    run = FakeRun(active="inactive")
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds

    assert cli.setup(env, run=run, probe=lambda path, timeout: False,
                     clock=lambda: now[0], sleep=sleep) == 1
    assert run.calls[-1][0] == [
        "journalctl", "--user", "-u", "omafind.service", "-n", "20", "--no-pager",
    ]
    assert "socket silent" in capsys.readouterr().err


def test_failed_runtime_build_does_not_download(cli, env):
    python = Path(env["HOME"]) / ".local/share/omafind/venv/bin/python"
    python.parent.mkdir(parents=True)
    python.touch()
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1)

    assert cli.main(["build-runtime"], env, run=run) == 1
    assert calls == [[str(ROOT / "scripts/build-runtime.sh")]]


def test_cli_import_needs_only_stdlib(env):
    result = subprocess.run(
        [sys.executable, "-S", "-c", "import runpy, sys; runpy.run_path(sys.argv[1])",
         str(ROOT / "bin/omafind")], env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_status_is_read_only(cli, env, monkeypatch, capsys):
    def create_data():
        raise PermissionError("Data directory is read-only")

    monkeypatch.setattr(cli.paths, "data_dir", create_data)
    assert cli.main(["status", "--json"], env, run=FakeRun(enabled="not-found", active="inactive"),
                    probe=lambda path, timeout: False) == 1
    details = json.loads(capsys.readouterr().out)
    assert details["runtime"]["present"] is False
    assert not (Path(env["XDG_DATA_HOME"]) / "omafind").exists()


def test_discover_json_prints_body_and_exits_0(cli, env, monkeypatch, capsys):
    from omafindd import discovery

    python = Path(env['HOME']) / '.local/share/omafind/venv/bin/python'
    monkeypatch.setattr(sys, 'prefix', str(python.parent.parent))
    body = {'home': env['HOME'], 'folders': []}
    calls = []

    def snapshot(**kwargs):
        calls.append(kwargs)
        return body

    monkeypatch.setattr(discovery, 'snapshot', snapshot)
    assert cli.main(['discover', '--json', '--volume', 'u'], env) == 0
    assert json.loads(capsys.readouterr().out) == body
    assert calls == [{'home': Path(env['HOME']), 'volume': 'u'}]
    assert cli.main(['discover'], env) == 2


def test_discover_failure_exits_1_with_one_stderr_line(cli, env, monkeypatch, capsys):
    from omafindd import discovery

    python = Path(env['HOME']) / '.local/share/omafind/venv/bin/python'
    monkeypatch.setattr(sys, 'prefix', str(python.parent.parent))

    def snapshot(**kwargs):
        raise OSError('scan failed\nmore details')

    monkeypatch.setattr(discovery, 'snapshot', snapshot)
    assert cli.main(['discover', '--json'], env) == 1
    assert capsys.readouterr().err.splitlines() == ['scan failed more details']


def test_reindex_incremental_passes_force_false(cli, env, monkeypatch):
    from omafindd import indexing
    from omafindd.settings import Settings

    python = Path(env['HOME']) / '.local/share/omafind/venv/bin/python'
    monkeypatch.setattr(sys, 'prefix', str(python.parent.parent))
    monkeypatch.setattr('omafindd.settings.load', lambda p: Settings(
        roots=[{'path': '/docs', 'volume': 'u', 'excludes': []}]))
    calls = []

    async def index(roots, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(indexing, 'reindex', index)
    assert cli.main(['reindex', '--incremental', '--volume', 'u'], env) == 0
    assert calls[0]['force'] is False
    assert calls[0]['volume'] == 'u'


@pytest.mark.parametrize('incremental,shared', [(True, True), (True, False), (False, False)])
def test_reindex_uses_shared_client_only_for_daemon_incremental(
        cli, env, monkeypatch, incremental, shared):
    from omafindd import indexing
    from omafindd.settings import Settings

    python = Path(env['HOME']) / '.local/share/omafind/venv/bin/python'
    monkeypatch.setattr(sys, 'prefix', str(python.parent.parent))
    monkeypatch.setattr('omafindd.settings.load', lambda p: Settings(
        roots=[{'path': '/docs', 'volume': 'u', 'excludes': []}]))
    if shared or not incremental:
        env.update(OMAFIND_EMBED_URL='http://127.0.0.1:1234', OMAFIND_EMBED_KEY='fixture-key')
    clients = []

    async def index(roots, **kwargs):
        clients.append(kwargs['embedder'])

    monkeypatch.setattr(indexing, 'reindex', index)
    args = ['reindex', '--volume', 'u', *(['--incremental'] if incremental else [])]
    assert cli.main(args, env) == 0
    assert clients[0].shared is shared


def test_discover_reexecs_into_installed_interpreter(cli, env):
    python = Path(env['HOME']) / '.local/share/omafind/venv/bin/python'
    python.parent.mkdir(parents=True)
    python.touch()
    calls = []

    def execve(path, argv, environment):
        calls.append((path, argv, environment))
        return 0

    assert cli.main(['discover', '--json', '--volume', 'u'], env, execve=execve) == 0
    assert calls == [(str(python), [str(python), str(ROOT / 'bin/omafind'),
                                   'discover', '--json', '--volume', 'u'], env)]


def test_discover_missing_interpreter_reports_one_line(cli, env, capsys):
    assert cli.main(['discover', '--json'], env) == 1
    assert capsys.readouterr().err.splitlines() == ['venv missing. Run bin/omafind setup.']


def test_discovery_modules_import_with_only_stdlib(env):
    result = subprocess.run([sys.executable, '-S', '-c',
                             'import sys; sys.path.insert(0, sys.argv[1]); '
                             'from omafindd import discovery, selection, rules',
                             str(ROOT / 'helper')],
                            env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_status_volumes_queue_and_health_are_read_only(cli, env, venv, capsys):
    import sqlite3

    data = Path(env['XDG_DATA_HOME']) / 'omafind'
    index = data / 'index'
    index.mkdir(parents=True)
    for uuid, label in (('u', 'Photos2024'), ('v', 'Backup'), ('code', 'code')):
        with sqlite3.connect(index / f'{uuid}.sqlite') as db:
            db.execute('CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)')
            db.execute("INSERT INTO meta VALUES('volume_label', ?)", (label,))
            db.execute('CREATE TABLE files(state TEXT, indexed_at REAL, detail TEXT)')
            db.executemany('INSERT INTO files VALUES(?, ?, ?)',
                           [('done', 1, None), ('partial', 2, None), ('pending', None, None),
                            ('partial', 3, 'permanent partial')])
    body = {'model': {'verified': True}, 'recovery': {'mode': 'reconcile'},
            'problems': [{'volume': 'v', 'problem': 'integrity', 'action': 'rebuilt'}]}
    (index / 'health.json').write_text(json.dumps(body))
    original = FakeRun()

    def run(command, **kwargs):
        if command == ['findmnt', '-rno', 'UUID']:
            return subprocess.CompletedProcess(command, 0, 'u\nu\n', '')
        return original(command, **kwargs)

    assert cli.main(['status', '--json'], env, run=run,
                    probe=lambda path, timeout: True) == 0
    details = json.loads(capsys.readouterr().out)
    assert details['volumes'] == [
        {'uuid': 'u', 'label': 'Photos2024', 'files': 3, 'online': True},
        {'uuid': 'v', 'label': 'Backup', 'files': 3, 'online': False}]
    assert details['queue'] == 4
    assert details['model']['verified'] is True
    assert details['recovery'] == body['recovery']
    assert details['problems'] == body['problems']
    assert cli.main(['status'], env, run=run, probe=lambda path, timeout: True) == 0
    lines = capsys.readouterr().out.splitlines()
    assert 'volume Photos2024 3 online' in lines
    assert 'volume Backup 3 offline' in lines
    assert 'queue 4' in lines
    assert 'recovery reconcile' in lines
    assert 'problem v integrity rebuilt' in lines


def test_status_modules_need_only_stdlib(env):
    result = subprocess.run([sys.executable, '-S', '-c',
                             'import runpy, sys; m = runpy.run_path(sys.argv[1]); '
                             'm["_index_status"](__import__("os").environ, '
                             'lambda *a, **k: __import__("subprocess").'
                             'CompletedProcess(a, 0, "", "")); '
                             'assert not any(n in sys.modules for n in '
                             '("omafindd.store", "omafindd.models", "numpy", "httpx"))',
                             str(ROOT / 'bin/omafind')],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_fingerprint_prints_the_plugin_build(cli, env, capsys):
    from omafindd import build

    assert cli.main(["fingerprint"], env) == 0
    assert capsys.readouterr().out == build.fingerprint(ROOT) + "\n"


@pytest.mark.parametrize("synced,state,code", [(True, "ready", 0), (False, "stale", 4)])
def test_status_checks_venv_against_lock(cli, env, venv, capsys, synced, state, code):
    class Run(FakeRun):
        def __call__(self, command, **kwargs):
            if command[0] == "uv":
                self.calls.append((command, kwargs))
                return subprocess.CompletedProcess(command, 0 if synced else 1, "", "outdated")
            return super().__call__(command, **kwargs)

    run = Run()
    assert cli.main(["status"], env, run=run, probe=lambda path, timeout: True) == code
    output = capsys.readouterr()
    assert f"venv {state}" in output.out.splitlines()
    assert output.err == ("" if synced else "next bin/omafind setup\n")
    [(command, kwargs)] = [call for call in run.calls if call[0][0] == "uv"]
    assert command == ["uv", "sync", "--project", str(ROOT / "helper"), "--frozen", "--no-dev",
                       "--offline", "--check"]
    assert kwargs["env"]["UV_PROJECT_ENVIRONMENT"] == str(venv)
    assert cli.main(["status", "--json"], env, run=run, probe=lambda path, timeout: True) == code
    assert json.loads(capsys.readouterr().out)["venv"] == {"path": str(venv), "state": state}


def test_status_reports_missing_venv_and_unknown_check(cli, env, capsys):
    assert cli.main(["status"], env, run=FakeRun(), probe=lambda path, timeout: True) == 4
    assert "venv missing" in capsys.readouterr().out.splitlines()
    python = Path(env["HOME"]) / ".local/share/omafind/venv/bin/python"
    python.parent.mkdir(parents=True)
    python.touch()

    def no_uv(command, **kwargs):
        if command[0] == "uv":
            raise FileNotFoundError("uv")
        return FakeRun()(command, **kwargs)

    assert cli.main(["status"], env, run=no_uv, probe=lambda path, timeout: True) == 4
    assert "venv unknown" in capsys.readouterr().out.splitlines()


def test_status_unit_codes_win_over_venv_but_keep_the_hint(cli, env, capsys):
    assert cli.main(["status"], env, run=FakeRun(active="inactive"),
                    probe=lambda path, timeout: False) == 2
    assert capsys.readouterr().err == "next bin/omafind setup\n"
