import subprocess

import pytest


@pytest.fixture
def env(tmp_path):
    directory = tmp_path / "bin"
    directory.mkdir()
    for name in ("omarchy-launch-editor", "omarchy-launch-browser"):
        path = directory / name
        path.write_text("fixture")
        path.chmod(0o755)
    return {"HOME": str(tmp_path), "PATH": str(directory)}


@pytest.mark.parametrize(
    "editor,tail",
    [
        ("nvim", ["-c", "41", "/tmp/a.txt"]),
        ("vim", ["-c", "41", "/tmp/a.txt"]),
        ("nano", ["+41", "/tmp/a.txt"]),
        ("micro", ["+41", "/tmp/a.txt"]),
        ("helix", ["/tmp/a.txt:41"]),
        ("unknown", ["/tmp/a.txt"]),
    ],
)
def test_text_editor_line_arguments(env, editor, tail):
    from pathlib import Path

    from omafindd.opener import command

    default = Path(env["HOME"]) / ".local/state/omarchy/defaults/editor"
    default.parent.mkdir(parents=True)
    default.write_text(editor + "\n")
    assert command({"kind": "text", "path": "/tmp/a.txt", "loc": 41}, env=env) == [
        "omarchy-launch-editor",
        *tail,
    ]


def test_extracted_text_skips_line(env):
    from omafindd.opener import command

    assert command(
        {"kind": "text", "path": "/tmp/a.html", "loc": 9, "info": {"extracted": True}}, env=env
    ) == ["omarchy-launch-editor", "/tmp/a.html"]


def test_pdf_browser_encodes_spaces_and_page(env):
    from omafindd.opener import command

    assert command({"kind": "pdf", "path": "/tmp/a b.pdf", "loc": 12}, env=env) == [
        "omarchy-launch-browser",
        "file:///tmp/a%20b.pdf#page=12",
    ]


def test_pdf_without_helper_falls_back(env):
    from omafindd.opener import command

    env["PATH"] = ""
    assert command({"kind": "pdf", "path": "/tmp/a.pdf", "loc": 12}, env=env) == [
        "xdg-open",
        "/tmp/a.pdf",
    ]


def test_other_kinds_use_xdg_open_with_injected_runner(env):
    from omafindd.opener import open_item

    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    open_item({"kind": "other", "path": "/tmp/a.bin"}, env=env, run=run)
    assert calls == [["xdg-open", "/tmp/a.bin"]]


def test_reveal_calls_showitems_with_fake_runner():
    from omafindd.opener import reveal

    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    reveal({"path": "/tmp/a b.pdf"}, run=run)
    assert calls == [
        [
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.freedesktop.FileManager1",
            "--object-path",
            "/org/freedesktop/FileManager1",
            "--method",
            "org.freedesktop.FileManager1.ShowItems",
            '["file:///tmp/a%20b.pdf"]',
            "",
        ]
    ]


@pytest.mark.parametrize("kind", ["video", "audio"])
@pytest.mark.parametrize("loc,expected", [(872.4, 872), (None, 0)])
def test_media_opens_at_second(env, kind, loc, expected):
    from omafindd.opener import command

    assert command({"kind": kind, "path": "/tmp/media", "loc": loc}, env=env) == [
        "mpv", f"--start={expected}", "/tmp/media",
    ]


@pytest.mark.parametrize("uwsm", [True, False])
@pytest.mark.parametrize("kind,how,tail", [
    ("audio", "open", ["mpv", "--start=12", "/tmp/media"]),
    ("image", "open", ["xdg-open", "/tmp/media"]),
    ("image", "reveal", ["nautilus", "--select", "/tmp/media"]),
])
def test_launch_moves_direct_apps_to_session_scope(env, monkeypatch, uwsm, kind, how, tail):
    from pathlib import Path

    from omafindd import opener

    if uwsm:
        binary = Path(env["PATH"]) / "uwsm-app"
        binary.write_text("fixture")
        binary.chmod(0o755)
    calls = []
    monkeypatch.setattr(opener.subprocess, "Popen", lambda argv, **kw: calls.append(argv))
    opener.launch({"kind": kind, "path": "/tmp/media", "loc": 12}, env=env, how=how)
    prefix = (["uwsm-app", "--"] if uwsm else
              ["systemd-run", "--user", "--scope", "--quiet", "--collect", "--"])
    assert calls == [prefix + tail]



def test_helix_path_with_colon_and_no_line_does_not_raise(tmp_path):
    state = tmp_path / ".local/state/omarchy/defaults"
    state.mkdir(parents=True)
    (state / "editor").write_text("hx\n")
    item = {"kind": "text", "path": "/notes/a:b.txt", "loc": None, "info": {}}
    from omafindd.opener import description

    assert description(item, env={"HOME": str(tmp_path)})["at"] is None
