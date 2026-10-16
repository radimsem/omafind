import json
import os
from pathlib import Path

import pytest
from omafindd import paths
from omafindd.settings import Settings, SettingsReader, load, normalize

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "tests/fixtures/settings-cases.json").read_text())


def write_settings(path, **fields):
    path.write_text(json.dumps({"plugins": [{"id": "radimsem.omafind", **fields}]}))


def test_example_has_exact_defaults():
    assert json.loads((ROOT / "settings.example.json").read_text()) == {
        "setupDone": False, "gpu": "auto", "audio": True,
        "roots": [], "maxResults": 40, "warmMinutes": 5,
        "imageBudget": 140, "shortcut": "SUPER + E", "ignoredVolumes": [],
    }


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_normalize_matches_shared_cases(case):
    settings = normalize(case["input"])
    assert {
        "setupDone": settings.setup_done, "gpu": settings.gpu, "audio": settings.audio,
        "roots": settings.roots, "ignoredVolumes": list(settings.ignored_volumes),
        "imageBudget": settings.image_budget, "maxResults": settings.max_results,
        "warmMinutes": settings.warm_minutes, "shortcut": settings.shortcut,
    } == case["expected"]


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


@pytest.mark.parametrize("key,value,expected", [("maxResults", 1, 10), ("maxResults", 999, 200),
                                              ("maxResults", True, 40),
                                              ("warmMinutes", -1, 0), ("warmMinutes", 80, 60),
                                              ("warmMinutes", "9", 5)])
def test_search_settings_clamp_without_coercion(tmp_path, key, value, expected):
    path = tmp_path / "shell.json"
    write_settings(path, **{key: value})
    assert getattr(load(path), "max_results" if key == "maxResults" else "warm_minutes") == expected


def test_roots_keep_valid_path_volume_and_excludes(tmp_path):
    path = tmp_path / "shell.json"
    write_settings(path, roots=[None, "bad", {"path": "/x", "volume": "v", "excludes": ["/x/no"]}])
    assert load(path).roots == [{"path": "/x", "volume": "v", "excludes": ["/x/no"]}]


@pytest.mark.parametrize("budget,expected", [(70, 70), (140, 140), (280, 280),
                                             (71, 140), (True, 140), ("280", 140)])
def test_image_budget_setting(tmp_path, budget, expected):
    path = tmp_path / "shell.json"
    write_settings(path, imageBudget=budget)
    assert load(path).image_budget == expected


def test_roots_and_setup_done_round_trip(tmp_path):
    path = tmp_path / 'shell.json'
    root = {'path': '/h/Documents', 'volume': 'u', 'excludes': ['tax/2024']}
    write_settings(path, setupDone=True, roots=[root])
    settings = load(path)
    assert settings.setup_done is True
    assert settings.roots == [root]


def test_legacy_code_roots_are_ignored(tmp_path):
    path = tmp_path / 'shell.json'
    write_settings(path, codeRoots=['/h/p/omaone', {'path': '/h/p/x', 'excludes': []}])
    assert load(path) == Settings()


@pytest.mark.parametrize('fields', [
    {'roots': '[{"path":"/h/Documents","volume":"u","excludes":[]}]'},
    {'roots': [{'path': '/h/Documents', 'excludes': []}]},
    {'roots': [{'path': '/h/Documents', 'volume': 'u', 'excludes': 'tax/2024'}]},
    {'roots': [{'path': 'Documents', 'volume': 'u', 'excludes': []}]},
    {'setupDone': 'true'},
])
def test_bad_root_shapes_give_defaults(tmp_path, fields):
    path = tmp_path / 'shell.json'
    write_settings(path, **fields)
    assert load(path) == Settings()


@pytest.mark.parametrize('value,expected', [
    (['usb', '', None, 42, 'other'], ('usb', 'other')), ('usb', ()), (None, ()),
])
def test_ignored_volumes_round_trip(tmp_path, value, expected):
    path = tmp_path / 'shell.json'
    write_settings(path, ignoredVolumes=value)
    assert load(path).ignored_volumes == expected
    assert SettingsReader(path).read().ignored_volumes == expected


def test_mount_aliases_rebase_roots_and_excludes_without_writing_shell(tmp_path, monkeypatch):
    from omafindd import health

    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    path = tmp_path / 'shell.json'
    write_settings(path, roots=[{'path': '/media/old/docs', 'volume': 'usb',
                                'excludes': ['/media/old/docs/private', 'generated']}])
    before = path.read_bytes()
    reader = SettingsReader(path)
    assert reader.read().roots[0]['path'] == '/media/old/docs'
    health.write(paths.health_path(), {'mounts': {'usb': {
        'current': '/media/new', 'previous': ['/media/old']}}})
    expected = [{'path': '/media/new/docs', 'volume': 'usb',
                 'excludes': ['/media/new/docs/private', 'generated']}]
    assert reader.read().roots == expected
    assert load(path).roots == expected
    assert SettingsReader(path).read().roots == expected
    assert path.read_bytes() == before
    health.write(paths.health_path(), {'mounts': {'usb': {
        'current': '/media/again', 'previous': ['/media/old', '/media/new']}}})
    assert reader.read().roots[0]['path'] == '/media/again/docs'


@pytest.mark.parametrize("value,valid", [("F9", True), ("F35", True), ("SUPER + F9", True),
                                         ("F36", False), ("F0", False), ("E", False),
                                         ("SUPER + SHIFT + SPACE", True)])
def test_shortcut_accepts_a_lone_function_key(value, valid):
    from omafindd.settings import valid_shortcut

    assert valid_shortcut(value) is valid
