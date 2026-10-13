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
    (plugin / "Service.qml").write_text("Item {}\n")
    assert build.fingerprint(plugin) == before


def test_state_message_carries_build():
    assert State(build="0.1.0+abc").message()["build"] == "0.1.0+abc"
    assert State().message()["build"] == ""


def test_missing_dependency_start_names_module_and_setup(tmp_path):
    code = ("import sys, runpy; sys.modules['watchdog'] = None; "
            "runpy.run_module('omafindd', run_name='__main__')")
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT / "helper",
                            env={"HOME": str(tmp_path), "PATH": "/usr/bin"},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert result.stderr.strip().splitlines() == [
        "omafindd cannot import watchdog. Run bin/omafind setup."]


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
