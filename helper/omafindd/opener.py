import json
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path


def command(item: Mapping, *, env: Mapping[str, str]) -> list[str]:
    path = item["path"]
    kind = item["kind"]
    if kind in ("text", "code") and shutil.which("omarchy-launch-editor", path=env.get("PATH")):
        default = Path(env["HOME"]) / ".local/state/omarchy/defaults/editor"
        try:
            editor = Path(default.read_text().strip().split()[0]).name
        except (OSError, IndexError):
            editor = "nvim"
        line = (item.get("open_line") or item.get("loc")) if kind == "code" else item.get("loc")
        if kind == "text" and (item.get("info", {}).get("extracted") or
                               Path(path).suffix.lower() in (".html", ".docx", ".odt")):
            line = None
        if line is not None:
            line = max(1, int(line))
            if editor in ("nvim", "vim", "nano", "micro"):
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
