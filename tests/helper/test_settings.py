import json
import os
from pathlib import Path

import pytest
from omafindd import paths
from omafindd.settings import Settings, SettingsReader, load

ROOT = Path(__file__).resolve().parents[2]


def write_settings(path, **fields):
    path.write_text(json.dumps({"plugins": [{"id": "radimsem.omafind", **fields}]}))


def test_example_has_exact_defaults():
    assert json.loads((ROOT / "settings.example.json").read_text()) == {
        "setupDone": False, "gpu": "auto", "audio": True,
    }


def test_load_reads_only_plugin_settings(tmp_path):
    path = tmp_path / "shell.json"
    path.write_text(json.dumps({"plugins": [
        {"id": "other", "gpu": "auto"},
        {"id": "radimsem.omafind", "setupDone": True, "gpu": "never", "audio": False,
         "roots": ["ignored"]},
    ]}))
    assert load(path) == Settings(setup_done=True, gpu="never", audio=False)


@pytest.mark.parametrize("value", [None, 0, 1, "false", [], {}])
def test_invalid_values_use_defaults(tmp_path, value):
    path = tmp_path / "shell.json"
    write_settings(path, setupDone=value, gpu=value, audio=value)
    assert load(path) == Settings()


@pytest.mark.parametrize("text", ['{"plugins":[]}', '{}', '[]', '{bad', '\udcff'])
def test_bad_config_uses_defaults(tmp_path, text):
    path = tmp_path / "shell.json"
    path.write_bytes(text.encode("utf-8", errors="surrogateescape"))
    assert load(path) == Settings()


def test_missing_file_uses_defaults_without_writing(tmp_path):
    path = tmp_path / "shell.json"
    assert load(path) == Settings()
    assert SettingsReader(path).read() == Settings()
    assert not path.exists()


@pytest.mark.parametrize("section", ["left", "center", "right"])
def test_load_finds_plugin_in_bar_layout(tmp_path, section):
    path = tmp_path / "shell.json"
    path.write_text(json.dumps({"bar": {"layout": {section: [
        "radimsem.omafind", {"id": "radimsem.omafind", "audio": False},
    ]}}}))
    assert load(path) == Settings(audio=False)


def test_reader_resets_when_file_is_removed(tmp_path):
    path = tmp_path / "shell.json"
    write_settings(path, gpu="never")
    reader = SettingsReader(path)
    assert reader.read().gpu == "never"
    path.unlink()
    assert reader.read() == Settings()


def test_reader_caches_then_reloads_changed_file(tmp_path, monkeypatch):
    path = tmp_path / "shell.json"
    write_settings(path, gpu="never")
    reader = SettingsReader(path)
    first = reader.read()

    def reject_read(self, *args, **kwargs):
        raise AssertionError("Unchanged settings were read again")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", reject_read)
        assert reader.read() is first
    previous = path.stat()
    write_settings(path, audio=False)
    os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000))
    assert reader.read() == Settings(audio=False)


def test_reader_keeps_last_good_settings_and_recovers(tmp_path, caplog):
    path = tmp_path / "shell.json"
    write_settings(path, gpu="never")
    reader = SettingsReader(path)
    assert reader.read().gpu == "never"
    path.write_text("{bad")
    assert reader.read().gpu == "never"
    assert reader.read().gpu == "never"
    assert len(caplog.records) == 1
    write_settings(path, audio=False)
    assert reader.read() == Settings(audio=False)


def test_paths_honour_environment_and_secure_data_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert paths.runtime_dir() == tmp_path / "run/omafind"
    assert paths.socket_path() == tmp_path / "run/omafind/ui.sock"
    plugin = tmp_path / "home/.config/omarchy/plugins/radimsem.omafind"
    assert paths.manifest_path() == plugin / "manifest.json"
    assert paths.shell_json_path() == tmp_path / "home/.config/omarchy/shell.json"
    assert paths.data_dir() == tmp_path / "home/.local/share/omafind"
    assert paths.data_dir().stat().st_mode & 0o777 == 0o700
    assert paths.runtime_bin() == paths.data_dir() / "runtime/bin/llama-server"
    assert paths.model_dir() == paths.data_dir() / "model"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    (tmp_path / "data/omafind").mkdir(parents=True, mode=0o755)
    assert paths.data_dir() == tmp_path / "data/omafind"
    assert paths.data_dir().stat().st_mode & 0o777 == 0o700


def test_runtime_directory_requires_user_session(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    with pytest.raises(ValueError, match="XDG_RUNTIME_DIR"):
        paths.runtime_dir()
