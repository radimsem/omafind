import shutil
import subprocess

import pytest

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


def fd_ten(argv, **kwargs):
    return subprocess.CompletedProcess(argv, 0, "fd 10.2.0\n", "")


def test_missing_build_lists_every_build_package():
    from omafindd.tools import missing_build

    assert missing_build(which=lambda name: None, exists=lambda path: False) == [
        "vulkan-headers", "shaderc", "gcc", "git", "uv"]


def test_missing_build_names_only_the_missing_package():
    from omafindd.tools import missing_build

    assert missing_build(which=lambda name: None if name == "glslc" else "/bin/" + name,
                         exists=lambda path: True) == ["shaderc"]
    assert missing_build(which=lambda name: "/bin/" + name,
                         exists=lambda path: False) == ["vulkan-headers"]


def test_check_build_reports_exactly_the_missing_packages(tmp_path):
    from omafindd.tools import TOOLS, check

    tools = tmp_path / "bin"
    tools.mkdir()
    for name in (*TOOLS, "c++"):
        (tools / name).write_text("#!/bin/sh\n")
        (tools / name).chmod(0o755)
    root = tmp_path / "root"
    probes = {"which": lambda name: shutil.which(name, path=str(tools)),
              "exists": lambda path: (root / path.lstrip("/")).exists()}
    assert check(run=fd_ten, **probes) == []
    assert check(run=fd_ten, build=True, **probes) == ["vulkan-headers", "shaderc", "uv"]
    header = root / "usr/include/vulkan/vulkan_core.h"
    header.parent.mkdir(parents=True)
    header.touch()
    assert check(run=fd_ten, build=True, **probes) == ["shaderc", "uv"]


def test_check_build_lists_a_shared_package_once():
    from omafindd.tools import check

    assert check(which=lambda name: None if name == "git" else "/bin/" + name, run=fd_ten,
                 exists=lambda path: True, build=True) == ["git"]


def test_setup_json_names_missing_runtime_tools(cli, env, capsys):
    import json

    assert cli.setup(env, run=fd_ten, which=lambda name: None, as_json=True) == 1
    output = capsys.readouterr()
    error = json.loads(output.out.splitlines()[-1])["error"]
    assert error["code"] == "tools-missing"
    assert error["fix"]["packages"] == output.err.split()[4:]


def test_setup_names_missing_build_packages_and_still_installs(cli, env, monkeypatch, capsys):
    import json

    from omafindd import tools
    from test_cli import FakeRun

    monkeypatch.setattr(tools, "missing_build", lambda **kwargs: ["vulkan-headers", "shaderc"])
    run = FakeRun(active="inactive")
    assert cli.setup(env, run=run, probe=lambda path, timeout: True,
                     which=lambda name: "/bin/" + name, as_json=True) == 0
    output = capsys.readouterr()
    assert output.err == ("Build packages missing: vulkan-headers, shaderc. "
                          "The search engine step in setup installs them.\n")
    assert json.loads(output.out.splitlines()[-1]) == {
        "ok": True, "build_missing": ["vulkan-headers", "shaderc"]}
    assert ["systemctl", "--user", "enable", "--now", "omafind.service"] in [
        command for command, _ in run.calls]


def test_setup_skips_build_packages_when_the_runtime_exists(cli, env, monkeypatch, capsys):
    import json

    from omafindd import paths, tools
    from test_cli import FakeRun

    def unexpected(**kwargs):
        raise AssertionError("an installed runtime needs no build packages")

    binary = paths.runtime_bin()
    binary.parent.mkdir(parents=True)
    binary.write_text("fake runtime")
    binary.chmod(0o755)
    monkeypatch.setattr(tools, "missing_build", unexpected)
    assert cli.setup(env, run=FakeRun(active="inactive"), probe=lambda path, timeout: True,
                     which=lambda name: "/bin/" + name, as_json=True) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out.splitlines()[-1]) == {"ok": True, "build_missing": []}


@pytest.mark.parametrize("args", [["status"], ["status", "--json"]])
def test_status_adds_build_packages_while_the_runtime_is_missing(cli, env, venv, monkeypatch,
                                                                  capsys, args):
    import json

    from omafindd import tools
    from test_cli import FakeRun

    monkeypatch.setattr(tools, "missing_build", lambda **kwargs: ["vulkan-headers", "shaderc"])
    assert cli.main(args, env, run=FakeRun(), probe=lambda *args: True) == 1
    output = capsys.readouterr()
    assert output.err.splitlines()[-1] == "sudo pacman -S --needed vulkan-headers shaderc"
    if "--json" in args:
        assert json.loads(output.out)["tools"] == {"missing": ["vulkan-headers", "shaderc"]}


def test_build_runtime_stops_on_missing_build_packages(cli, env, venv, monkeypatch, capsys):
    from omafindd import tools

    def run(*args, **kwargs):
        raise AssertionError("the build must not start")

    monkeypatch.setattr(tools, "missing_build", lambda **kwargs: ["vulkan-headers", "shaderc"])
    assert cli.main(["build-runtime"], env, run=run) == 1
    assert capsys.readouterr().err == "sudo pacman -S --needed vulkan-headers shaderc\n"


def test_every_extraction_tool_says_what_it_gives_and_has_a_package():
    from omafindd.tools import TOOL_FEATURES, TOOLS

    assert set(TOOL_FEATURES) == {
        "magick", "pdfinfo", "pdftotext", "pdftoppm", "ffprobe", "ffmpeg", "tesseract"
    }
    assert set(TOOL_FEATURES) <= set(TOOLS)
