import fnmatch
import os
import re
import subprocess
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

INDEXED_KINDS = {
    "text": ("md", "txt", "html", "docx", "odt"), "pdf": ("pdf",),
    "image": ("jpg", "jpeg", "png", "webp", "heic", "heif", "avif", "gif", "bmp", "tif", "tiff"),
    "video": ("mp4", "m4v", "mov", "mkv", "webm", "avi", "mpg", "mpeg", "ogv"),
    "audio": ("wav", "mp3", "m4a", "aac", "flac", "ogg", "opus", "aiff", "aif", "wma"),
}
SIZE_CAPS = {"pdf": 512, "video": 8192, "audio": 2048}
SCREEN_SIZES = {
    (1280, 720), (1366, 768), (1440, 900), (1600, 900), (1920, 1080), (1920, 1200),
    (2560, 1440), (2560, 1600), (2880, 1800), (3440, 1440), (3840, 2160), (5120, 2880),
}
HEAVY_GLOBS = (
    "node_modules",
    "bower_components",
    ".git",
    "target",
    "build",
    "dist",
    "venv",
    ".venv",
    "site-packages",
    "__pycache__",
    "DerivedData",
    "Pods",
    "Carthage",
    "cache",
    "caches",
    ".cache",
)
_SECRET_TYPES = (
    "pem",
    "key",
    "p12",
    "pfx",
    "keystore",
    "jks",
    "ppk",
    "kdbx",
    "gpg",
    "age",
    "asc",
    "crt",
    "cer",
    "der",
    "p8",
    "mobileprovision",
)
_SECRET_PREFIXES = (
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    ".env",
    "secret",
    "credential",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "htpasswd",
    ".htpasswd",
)
# fd override globs are case-sensitive; DigUp's secret predicate is not.
SECRET_GLOBS = tuple(
    "".join(f"[{c.lower()}{c.upper()}]" if c.isalpha() else c for c in glob)
    for glob in [
        *(f"*.{ext}" for ext in _SECRET_TYPES),
        *(f"{prefix}*" for prefix in _SECRET_PREFIXES),
    ]
)
_CAMERA_PREFIXES = (
    "img",
    "dsc",
    "pxl",
    "mvimg",
    "vid",
    "gopr",
    "dji",
    "photo",
    "whatsapp",
    "screenshot",
)


@dataclass(frozen=True)
class Skip:
    path: Path
    rule: str


def classify(path: Path) -> str | None:
    ext = path.suffix[1:].lower()
    return next((kind for kind, extensions in INDEXED_KINDS.items() if ext in extensions), None)


def screenshot_like(name: str, width: int, height: int) -> bool:
    return name.lower().startswith(("screenshot", "screen shot", "cleanshot", "scr-")) or (
        (width, height) in SCREEN_SIZES or (height, width) in SCREEN_SIZES
    )


def reason(path: Path) -> str | None:
    if any(fnmatch.fnmatchcase(part, glob) for part in path.parts for glob in SECRET_GLOBS):
        return "secrets"
    if any(part in HEAVY_GLOBS for part in path.parts):
        return "heavy"
    if any(part.startswith(".") and part not in (".", "..") for part in path.parts):
        return "dot"
    return None


def fd_args(root: Path, *, excludes: Sequence[str], kinds: Iterable[str]) -> list[str]:
    args = ["fd", "-0", "-t", "f", "--one-file-system", "--no-global-ignore-file"]
    for kind in kinds:
        for extension in INDEXED_KINDS[kind]:
            args.extend(["-e", extension])
    for glob in (*HEAVY_GLOBS, *SECRET_GLOBS):
        args.extend(["-E", glob])
    for excluded in excludes:
        path = Path(excluded)
        if path.is_absolute():
            try:
                excluded = "/" + path.relative_to(root).as_posix()
            except ValueError:
                continue
        args.extend(["-E", excluded, "-E", excluded.rstrip("/") + "/**"])
    if reason(root.absolute()) is not None:
        # fd ignores the starting directory's name when applying override globs.
        args.extend(["-E", "*"])
    return [*args, ".", str(root)]


def walk(root: Path, *, excludes: Sequence[str], run=subprocess.Popen) -> Iterator[Path]:
    args = fd_args(root, excludes=excludes, kinds=INDEXED_KINDS)
    with run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=root) as process:
        pending = b""
        while block := process.stdout.read(65536):
            pieces = (pending + block).split(b"\0")
            pending = pieces.pop()
            for piece in pieces:
                yield Path(os.fsdecode(piece))
        error = process.stderr.read()
        if process.wait():
            raise OSError(f"fd failed: {os.fsdecode(error).strip()}")


def looks_machine_named(stem: str) -> bool:
    name = stem.lower()
    return not name.startswith(_CAMERA_PREFIXES) and bool(
        re.fullmatch(r"[0-9a-f]{8,}([-_][0-9a-f]{4,})*", name)
        or re.fullmatch(r"[a-z]{0,16}[-_. ]?\d{3,}([-_.]\d+)*", name)
    )


def keep(paths: Iterable[Path], *, root: Path) -> Iterator[Path | Skip]:
    paths = list(paths)
    groups = defaultdict(list)
    for path in paths:
        if path.parent != root:
            groups[path.parent, classify(path)].append(path.stem)
    datasets = {
        folder
        for (folder, _), stems in groups.items()
        if len(stems) >= 300 and sum(map(looks_machine_named, stems)) / len(stems) >= 0.7
    }
    for path in paths:
        if any(folder == path.parent or folder in path.parents for folder in datasets):
            yield Skip(path, "dataset")
            continue
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            continue
        cap = SIZE_CAPS.get(classify(path), 16) * 1024 * 1024
        yield Skip(path, "size-cap") if size > cap else path


def explain(root: Path, *, run=subprocess.run) -> dict[str, int]:
    args = fd_args(root, excludes=[], kinds=INDEXED_KINDS)

    def listing(argv):
        result = run(argv, cwd=root, capture_output=True, check=True)
        return set(result.stdout.split(b"\0")) - {b""}

    baseline = listing(args)
    counts = {"dot": len(listing([args[0], "-H", *args[1:]]) - baseline)}
    for rule, globs in (("heavy", HEAVY_GLOBS), ("secrets", SECRET_GLOBS)):
        relaxed = []
        index = 0
        while index < len(args):
            if args[index] == "-E" and args[index + 1] in globs:
                index += 2
            else:
                relaxed.append(args[index])
                index += 1
        counts[rule] = len(listing(relaxed) - baseline)
    return counts
