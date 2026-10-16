import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from omafindd import build
from omafindd.state import State

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def plugin(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"version": "0.2.0"}))
    package = tmp_path / "helper/omafindd"
    package.mkdir(parents=True)
    (tmp_path / "helper/uv.lock").write_text("lock 1\n")
    (tmp_path / "helper/pyproject.toml").write_text("[project]\n")
    (tmp_path / "settings.example.json").write_text('{"maxResults": 40}\n')
    (tmp_path / "systemd").mkdir()
    (tmp_path / "systemd/omafind.service").write_text("[Service]\n")
    (package / "__init__.py").write_text("")
    (package / "main.py").write_text("x = 1\n")
    return tmp_path


def test_fingerprint_is_manifest_version_plus_hash(plugin):
    assert re.fullmatch(r"0\.2\.0\+[0-9a-f]{12}", build.fingerprint(plugin))
    assert build.fingerprint(plugin) == build.fingerprint(plugin)


@pytest.mark.parametrize("change", [
    lambda root: (root / "helper/uv.lock").write_text("lock 2\n"),
    lambda root: (root / "helper/pyproject.toml").write_text("[project]\nname = 'x'\n"),
    lambda root: (root / "helper/omafindd/main.py").write_text("x = 2\n"),
    lambda root: (root / "helper/omafindd/new.py").write_text(""),
    lambda root: (root / "helper/omafindd/main.py").rename(root / "helper/omafindd/other.py"),
    lambda root: (root / "manifest.json").write_text(json.dumps({"version": "0.2.1"})),
    lambda root: (root / "settings.example.json").write_text('{"maxResults": 50}\n'),
    lambda root: (root / "systemd/omafind.service").write_text("[Service]\nEnvironment=X=1\n"),
])
def test_fingerprint_changes_with_daemon_code_lock_or_version(plugin, change):
    before = build.fingerprint(plugin)
    change(plugin)
    assert build.fingerprint(plugin) != before


def test_fingerprint_ignores_bytecode_and_plugin_qml(plugin):
    before = build.fingerprint(plugin)
    cache = plugin / "helper/omafindd/__pycache__"
    cache.mkdir()
    (cache / "main.cpython-312.pyc").write_bytes(b"\0")
    (plugin / "ui").mkdir()
    (plugin / "ui/Service.qml").write_text("Item {}\n")
    assert build.fingerprint(plugin) == before


def test_state_message_carries_build():
    assert State(build="0.1.0+abc").message()["build"] == "0.1.0+abc"
    assert State().message()["build"] == ""


def test_missing_dependency_start_names_module_and_setup(tmp_path):
    code = ("import sys, runpy; sys.modules['inotify_simple'] = None; "
            "runpy.run_module('omafindd', run_name='__main__')")
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT / "helper",
                            env={"HOME": str(tmp_path), "PATH": "/usr/bin"},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert result.stderr.strip().splitlines() == [
        "omafindd cannot import inotify_simple. Run bin/omafind setup."]
    log = tmp_path / ".local/share/omafind/cache/logs/omafindd-start.log"
    assert log.read_text().endswith(
        " omafindd cannot import inotify_simple. Run bin/omafind setup.\n")
    assert log.stat().st_mode & 0o777 == 0o600


def test_fingerprint_rejects_manifest_without_version(plugin):
    (plugin / "manifest.json").write_text("{}")
    with pytest.raises(ValueError):
        build.fingerprint(plugin)


async def test_daemon_reports_empty_build_when_fingerprint_fails(tmp_path, monkeypatch, caplog):
    from omafindd import main

    def broken(root):
        raise OSError("file vanished")

    started = []

    class Server:
        def __init__(self, path, state):
            started.append(state.build)
            raise main.AlreadyRunning("stop here")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(main.build, "fingerprint", broken)
    monkeypatch.setattr(main, "IpcServer", Server)
    manifest = tmp_path / "manifest.json"
    manifest.touch()
    with pytest.raises(main.AlreadyRunning):
        await main._serve(manifest)
    assert started == [""]
    assert "Cannot fingerprint" in caplog.text


def test_fatal_start_error_writes_the_start_log(tmp_path, monkeypatch):
    from omafindd import main, paths, startlog

    async def bind_fails():
        raise OSError(98, "Address already in use")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(main, "_serve", bind_fails)
    assert main.run() == 1
    assert "Address already in use" in (paths.logs_dir() / startlog.NAME).read_text()


def test_start_log_write_never_raises(tmp_path, monkeypatch):
    from omafindd import startlog

    (tmp_path / "file").touch()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "file"))
    startlog.write("bind failed")
    startlog.clear()


async def test_started_daemon_removes_the_start_log(tmp_path, monkeypatch):
    from omafindd import main, paths, startlog

    class Server:
        def __init__(self, path, state):
            self.state = state

        async def start(self):
            assert stale.exists()

        async def stop(self):
            pass

        async def broadcast(self, message):
            pass

    def stop_here():
        raise main.AlreadyRunning("stop here")

    class Freshness(main._Freshness):
        def __init__(self, *args):
            super().__init__(*args)
            self.volumes.snapshot = stop_here

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(main, "IpcServer", Server)
    monkeypatch.setattr(main, "_Freshness", Freshness)
    stale = paths.logs_dir() / startlog.NAME
    stale.write_text("old failure\n")
    manifest = tmp_path / "manifest.json"
    manifest.touch()
    assert await main._serve(manifest) == 1
    assert not stale.exists()
