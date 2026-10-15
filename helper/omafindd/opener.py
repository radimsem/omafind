import json
import os
import shlex
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path


def editor_name(*, env: Mapping[str, str]) -> str:
    default = Path(env["HOME"]) / ".local/state/omarchy/defaults/editor"
    try:
        return Path(shlex.split(default.read_text().splitlines()[0])[0]).name
    except (OSError, IndexError, ValueError):
        return "nvim"


def command(item: Mapping, *, env: Mapping[str, str]) -> list[str]:
    path = item["path"]
    kind = item["kind"]
    if kind in ("video", "audio"):
        return ["mpv", f"--start={int(item.get('loc') or 0)}", path]
    if kind in ("text", "code") and shutil.which("omarchy-launch-editor", path=env.get("PATH")):
        editor = editor_name(env=env)
        line = (item.get("open_line") or item.get("loc")) if kind == "code" else item.get("loc")
        if kind == "text" and (item.get("info", {}).get("extracted") or
                               Path(path).suffix.lower() in (".html", ".docx", ".odt")):
            line = None
        if line is not None:
            line = max(1, int(line))
            # Ghostty drops a "+N" argument after -e, so vim and nvim get the line as a command.
            if editor in ("nvim", "vim"):
                return ["omarchy-launch-editor", "-c", str(line), path]
            if editor in ("nano", "micro"):
                return ["omarchy-launch-editor", f"+{line}", path]
            if editor in ("helix", "hx"):
                return ["omarchy-launch-editor", f"{path}:{line}"]
        return ["omarchy-launch-editor", path]
    if kind == "pdf" and shutil.which("omarchy-launch-browser", path=env.get("PATH")):
        uri = Path(path).as_uri()
        if item.get("loc") is not None:
            uri += f"#page={max(1, int(item['loc']))}"
        return ["omarchy-launch-browser", uri]
    return ["xdg-open", path]


def reveal_command(item: Mapping) -> list[str]:
    return [
        "gdbus",
        "call",
        "--session",
        "--dest",
        "org.freedesktop.FileManager1",
        "--object-path",
        "/org/freedesktop/FileManager1",
        "--method",
        "org.freedesktop.FileManager1.ShowItems",
        json.dumps([Path(item["path"]).as_uri()]),
        "",
    ]


def open_item(item: Mapping, *, env: Mapping[str, str], run=subprocess.run):
    return run(command(item, env=env), env=env, check=False)


def reveal(item: Mapping, *, run=subprocess.run):
    result = run(reveal_command(item), check=False)
    if result.returncode:
        return run(["nautilus", "--select", item["path"]], check=False)
    return result


def description(item: Mapping, *, env=None, how="open") -> dict:
    env = os.environ if env is None else env
    if how == "reveal":
        return {"opener": "nautilus --select", "at": None}
    argv = command(item, env=env)
    label = argv[0]
    kind, loc = item["kind"], item.get("loc")
    at = None
    if kind in ("video", "audio"):
        seconds = int(loc or 0)
        label += f" --start={seconds}"
        at = f"{seconds // 60}:{seconds % 60:02}"
    elif kind == "pdf" and loc is not None:
        at = f"p. {max(1, int(loc))}"
    elif kind in ("text", "code"):
        line = item.get("open_line") or loc if kind == "code" else loc
        if line is not None:
            at = f"L{max(1, int(line))}"
        if argv[0] == "omarchy-launch-editor":
            label = editor_name(env=env)
            helix = label in ("hx", "helix") and ":" in argv[-1]
            if line is not None and (len(argv) > 2 or helix):
                label += f" +{max(1, int(line))}"
            else:
                # Extracted html, docx and odt open without a line.
                at = None
    return {"opener": label, "at": at}


def launch(item: Mapping, *, how="open", env=None):
    env = os.environ if env is None else env
    argv = ["nautilus", "--select", item["path"]] if how == "reveal" else command(item, env=env)
    if argv[0] in ("mpv", "xdg-open", "nautilus"):
        prefix = (["uwsm-app", "--"] if shutil.which("uwsm-app", path=env.get("PATH")) else
                  ["systemd-run", "--user", "--scope", "--quiet", "--collect", "--"])
        argv = prefix + argv
    return subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
