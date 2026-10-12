import re
import shutil
import subprocess

TOOLS = {
    "fd": "fd",
    "rg": "ripgrep",
    "magick": "imagemagick",
    "pdfinfo": "poppler",
    "pdftotext": "poppler",
    "pdftoppm": "poppler",
    "git": "git",
    "findmnt": "util-linux",
}


def missing_tools(which=shutil.which) -> list[str]:
    return list(dict.fromkeys(package for tool, package in TOOLS.items() if not which(tool)))


def check(*, which=shutil.which, run=subprocess.run) -> list[str]:
    missing = missing_tools(which)
    if "fd" not in missing:
        result = run(["fd", "--version"], capture_output=True, text=True)
        version = re.search(r"\bfd\s+(\d+)", result.stdout)
        if result.returncode or version is None or int(version[1]) < 10:
            missing.insert(0, "fd")
    return missing
