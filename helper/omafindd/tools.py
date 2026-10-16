import os
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
    "ffmpeg": "ffmpeg",
    "ffprobe": "ffmpeg",
    "tesseract": "tesseract",
}

# What a file is indexed without when the tool is missing (errors.tool_missing `what`).
TOOL_FEATURES = {
    "magick": "image support",
    "pdfinfo": "PDF text",
    "pdftotext": "PDF text",
    "pdftoppm": "PDF page images",
    "ffprobe": "video and audio",
    "ffmpeg": "video and audio",
    "tesseract": "text recognition",
}

# cmake, ninja and spirv-headers stay out: scripts/build-runtime.sh falls back to private copies.
BUILD_NEEDS = [
    ("header", "/usr/include/vulkan/vulkan_core.h", "vulkan-headers"),
    ("command", "glslc", "shaderc"),
    ("command", "c++", "gcc"),
    ("command", "git", "git"),
    ("command", "uv", "uv"),
]


def missing_tools(which=shutil.which) -> list[str]:
    return list(dict.fromkeys(package for tool, package in TOOLS.items() if not which(tool)))


def missing_build(*, which=shutil.which, exists=os.path.exists) -> list[str]:
    found = {"header": exists, "command": which}
    return list(dict.fromkeys(
        package for kind, target, package in BUILD_NEEDS if not found[kind](target)))


def check(*, which=shutil.which, run=subprocess.run, build=False,
          exists=os.path.exists) -> list[str]:
    missing = missing_tools(which)
    if "fd" not in missing:
        result = run(["fd", "--version"], capture_output=True, text=True)
        version = re.search(r"\bfd\s+(\d+)", result.stdout)
        if result.returncode or version is None or int(version[1]) < 10:
            missing.insert(0, "fd")
    if build:
        missing += [package for package in missing_build(which=which, exists=exists)
                    if package not in missing]
    return missing
