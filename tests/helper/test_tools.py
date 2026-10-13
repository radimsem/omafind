import subprocess

pytest_plugins = ("test_cli",)


def test_missing_tools_deduplicate_pacman_packages():
    from omafindd.tools import missing_tools

    assert missing_tools(which=lambda name: None) == [
        "fd",
        "ripgrep",
        "imagemagick",
        "poppler",
        "git",
        "util-linux",
        "ffmpeg",
        "tesseract",
    ]


def test_fd_ten_is_required():
    from omafindd.tools import check

    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "fd 9.0.0\n", "")

    assert check(which=lambda name: "/bin/" + name, run=run) == ["fd"]


def test_setup_missing_tool_exits_before_installing(cli, env, capsys):
    def reject(*args, **kwargs):
        raise AssertionError("setup must check tools first")

    assert cli.setup(env, run=reject, which=lambda name: None) == 1
    lines = capsys.readouterr().err.splitlines()
    assert lines == [
        "sudo pacman -S --needed fd ripgrep imagemagick poppler git util-linux ffmpeg tesseract"
    ]


def test_status_json_reports_tools(cli, env, venv, capsys):
    import json

    from test_cli import FakeRun

    assert cli.main(["status", "--json"], env, run=FakeRun(), probe=lambda *args: True) == 0
    assert json.loads(capsys.readouterr().out)["tools"] == {"missing": []}
