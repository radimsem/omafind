import json
import subprocess
from pathlib import Path

import pytest
from omafindd import bindings

pytest_plugins = ("test_cli",)


def test_owned_block_write_replace_remove(tmp_path):
    path = tmp_path / "bindings.lua"
    original = '-- keep\no.bind("SUPER + B", "Browser", "firefox")\n'
    path.write_text(original)
    assert bindings.write_block(path, "SUPER + E")
    assert not bindings.write_block(path, "SUPER + E")
    assert bindings.write_block(path, "SUPER + D")
    assert path.read_text().count("-- omafind-shortcut-start") == 1
    assert 'o.bind("SUPER + D", "omafind", ' in path.read_text()
    assert bindings.check("SUPER + D", bindings.parse_binds(path.read_text())) == "ours"
    assert bindings.remove_block(path)
    assert not bindings.remove_block(path)
    assert path.read_text() == original


def test_parse_live_binds_conflict_overrides_ours():
    values = [{"modmask": 66, "key": "e", "description": "omafind",
               "dispatcher": "__lua", "arg": "64"},
              {"modmask": 64, "key": "E", "description": "Email"}]
    parsed = bindings.parse_binds(json.dumps(values))
    assert bindings.check("SUPER + E", parsed[:1]) == "ours"
    assert bindings.check("SUPER + E", parsed) == "conflict"
    assert bindings.check("SUPER + D", parsed) == "free"
    values[0]["description"] = "another-app"
    assert bindings.check("SUPER + E", bindings.parse_binds(json.dumps(values[:1]))) == "conflict"


def test_cli_conflict_names_the_holder_without_suggesting(cli, env, capsys):
    values = [{"modmask": 64, "key": "E", "description": "Taken"}]

    def run(argv, **kwargs):
        assert argv == ["hyprctl", "binds", "-j"]
        assert kwargs["timeout"]
        return subprocess.CompletedProcess(argv, 0, json.dumps(values), "")

    assert cli.main(["bindings", "check", "--chord", "SUPER + E"], env, run=run) == 2
    assert capsys.readouterr().out == "Super E is taken by Taken.\n"


def test_binds_items_label_chords_and_skip_ours_and_empty_keys():
    values = [{"modmask": 64, "key": "e", "description": "omafind"},
              {"modmask": 65, "key": "SPACE", "description": "Launcher"},
              {"modmask": 76, "key": "h", "description": "Hardware"},
              {"modmask": 64, "key": "", "description": "Workspace"},
              {"modmask": 0, "key": "F9", "description": ""},
              {"modmask": 65, "key": "space", "description": "Second"},
              {"modmask": 64, "key": "R", "description": "resize", "submap": "resize"}]
    assert bindings.binds_items(bindings.parse_binds(json.dumps(values))) == [
        {"chord": "Super Shift Space", "description": "Launcher"},
        {"chord": "Super Ctrl Alt H", "description": "Hardware"},
        {"chord": "F9", "description": ""},
    ]


def test_cli_checks_file_when_hyprctl_missing(cli, env, capsys):
    path = Path(env["XDG_CONFIG_HOME"]) / "hypr/bindings.lua"
    path.parent.mkdir(parents=True)
    bindings.write_block(path, "SUPER + E")

    def run(*args, **kwargs):
        raise FileNotFoundError("hyprctl")

    assert cli.main(["bindings", "check"], env, run=run) == 0
    assert capsys.readouterr().out == "Super E is bound by omafind.\n"


OURS = json.dumps([{"modmask": 64, "key": "E", "description": "omafind"}])


@pytest.mark.parametrize("live,reloads", [(OURS, 0), ("[]", 1)])
def test_cli_write_reloads_only_when_hyprland_missed_the_change(cli, env, monkeypatch,
                                                                 live, reloads):
    # Hyprland reloads by itself when bindings.lua changes, and each reload resets monitor
    # scales set at runtime.
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, live, "")

    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    assert cli.main(["bindings", "write"], env, run=run) == 0
    assert calls.count(["hyprctl", "reload"]) == reloads
    assert ["hyprctl", "binds", "-j"] in calls


@pytest.mark.parametrize("live,reloads", [("[]", 0), (OURS, 1)])
def test_cli_remove_reloads_only_when_hyprland_missed_the_change(cli, env, monkeypatch,
                                                                  live, reloads):
    path = Path(env["XDG_CONFIG_HOME"]) / "hypr/bindings.lua"
    path.parent.mkdir(parents=True)
    bindings.write_block(path, "SUPER + E")
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, live, "")

    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    assert cli.main(["bindings", "remove"], env, run=run) == 0
    assert calls.count(["hyprctl", "reload"]) == reloads


def test_cli_unchanged_binding_calls_no_hyprctl(cli, env):
    path = Path(env["XDG_CONFIG_HOME"]) / "hypr/bindings.lua"
    path.parent.mkdir(parents=True)
    bindings.write_block(path, "SUPER + E")
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "[]", "")

    assert cli.main(["bindings", "write"], env, run=run) == 0
    path.unlink()
    assert cli.main(["bindings", "remove"], env, run=run) == 0
    assert calls == []


@pytest.mark.parametrize("original", ['{\n  // keep\n  "other": {"label":"Other"}\n}\n',
                                      '{}\n', '{\n // empty\n}\n',
                                      '// example { keep\n{\n // empty\n}\n'])
def test_menu_preserves_comments_and_existing_lines(tmp_path, original):
    path = tmp_path / "menu.jsonc"
    path.write_text(original)
    assert bindings.write_menu_row(path)
    assert not bindings.write_menu_row(path)
    result = path.read_text()
    assert '"label":"Find files"' in result
    assert result.count("// omafind-menu-start") == 1
    import re

    assert "find" in json.loads(re.sub(r",\s*}", "}",
                                      re.sub(r"(?m)^\s*//.*$", "", result)))
    assert bindings.remove_menu_row(path)
    assert not bindings.remove_menu_row(path)
    assert path.read_text() == original


def test_has_menu_row_reads_the_marked_block(tmp_path):
    path = tmp_path / "menu.jsonc"
    assert not bindings.has_menu_row(path)
    path.write_text('{\n  // omafind-menu-start mentioned in a comment\n}\n')
    assert not bindings.has_menu_row(path)
    path.write_text('{\n// omafind-menu-start\n}\n')
    assert not bindings.has_menu_row(path)
    path.write_text('{}\n')
    bindings.write_menu_row(path)
    assert bindings.has_menu_row(path)
    bindings.remove_menu_row(path)
    assert not bindings.has_menu_row(path)


@pytest.mark.parametrize("chord", ["SUPER + mouse:272", "SUPER + XF86AudioMute",
                                    "SUPER + code:10", "SUPER + e", "E"])
def test_lua_skips_unsupported_chords(chord):
    text = f'o.bind("{chord}", "other", "command")\n' + bindings.render_block("SUPER + E")
    assert bindings.check("SUPER + E", bindings.parse_binds(text)) == "ours"


def test_live_submap_binds_do_not_occupy_global_chord():
    text = json.dumps([{"modmask": 64, "key": "E", "description": "resize",
                        "submap": "resize"}])
    assert bindings.check("SUPER + E", bindings.parse_binds(text)) == "free"
