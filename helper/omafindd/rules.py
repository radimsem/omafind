import fnmatch
import os
import re
import subprocess
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from functools import lru_cache
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

MEDIA_KINDS = ("image", "video", "audio")
# ISO-date stems are camera and phone exports.
_ISO_DATE = re.compile(
    r"(?:\d{4}-\d{2}-\d{2}(?:[-_ T.].*)?|"
    r"(?:19|20)\d\d(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?:[-_ T.]?.*)?)"
)


@dataclass(frozen=True)
class Skip:
    path: Path
    rule: str


_KINDS_BY_EXT = {ext: kind for kind, exts in INDEXED_KINDS.items() for ext in exts}


def classify(path: Path) -> str | None:
    return _KINDS_BY_EXT.get(path.suffix[1:].lower())


def classify_name(name: str) -> str | None:
    index = name.rfind('.')
    return _KINDS_BY_EXT.get(name[index + 1:].lower()) if index > 0 else None


def screenshot_like(name: str, width: int, height: int) -> bool:
    return name.lower().startswith(("screenshot", "screen shot", "cleanshot", "scr-")) or (
        (width, height) in SCREEN_SIZES or (height, width) in SCREEN_SIZES
    )


_SECRET_PATTERN = re.compile("|".join(fnmatch.translate(glob) for glob in SECRET_GLOBS))


@lru_cache(maxsize=65536)
def _part_reason(part: str) -> str | None:
    if _SECRET_PATTERN.match(part):
        return "secrets"
    if part in HEAVY_GLOBS:
        return "heavy"
    if part.startswith('.') and part not in ('.', '..'):
        return "dot"
    return None


@lru_cache(maxsize=65536)
def _parts_reason(parts: tuple[str, ...]) -> str | None:
    if not parts:
        return None
    if len(parts) > 256:
        reasons = {_part_reason(part) for part in parts}
        return next((rule for rule in ('secrets', 'heavy', 'dot') if rule in reasons), None)
    parent = _parts_reason(parts[:-1])
    own = _part_reason(parts[-1])
    if 'secrets' in (parent, own):
        return 'secrets'
    if 'heavy' in (parent, own):
        return 'heavy'
    return parent or own


def reason(path: Path) -> str | None:
    return _parts_reason(path.parts)


def reason_parts(parts: tuple[str, ...]) -> str | None:
    return _parts_reason(parts)


def reason_name(name: str) -> str | None:
    return _part_reason(name)


def _rx(value: str) -> str:
    return ''.join('\\' + char if char in r'\.+*?()|[]{}^$#&-~' else char for char in value)


def fd_args(
    root: Path, *, excludes: Sequence[str], kinds: Iterable[str], only: Sequence[Path] | None = None
) -> list[str]:
    args = ["fd", "--threads", "8", "-0", "-t", "f", "--one-file-system", "--no-global-ignore-file"]
    for kind in kinds:
        for extension in INDEXED_KINDS[kind]:
            args.extend(["-e", extension])
    for glob in (*HEAVY_GLOBS, *SECRET_GLOBS):
        args.extend(["-E", glob])
    for excluded in excludes:
        excluded = exclude_rel(root, excluded)
        if excluded is None:
            continue
        escaped = "".join(f"[{c}]" if c in "[]*?{}" else c for c in excluded)
        anchored = "/" + escaped
        args.extend(["-E", anchored, "-E", anchored.rstrip("/") + "/**"])
    if reason(root.absolute()) is not None:
        # fd ignores the starting directory's name when applying override globs.
        args.extend(["-E", "*"])
    if only is not None:
        pattern = '^(?:' + '|'.join(_rx(str(path.resolve()).rstrip('/')) for path in only) + ')/'
        return [*args, '--full-path', '-s', pattern if only else '^$', str(root)]
    return [*args, ".", str(root)]


def walk(
    root: Path, *, excludes: Sequence[str], run=subprocess.Popen,
    only: Sequence[Path] | None = None, kinds: Iterable[str] = INDEXED_KINDS,
) -> Iterator[Path]:
    if only is not None:
        # The --full-path pattern holds resolved paths, so fd must see the resolved root too.
        root = root.resolve()
    args = fd_args(root, excludes=excludes, kinds=kinds, only=only)
    # fd can fill a stderr pipe before it closes stdout, blocking both readers.
    with tempfile.TemporaryFile() as errors, run(
        args, stdout=subprocess.PIPE, stderr=errors, cwd=root
    ) as process:
        pending = b""
        while block := process.stdout.read(65536):
            pieces = (pending + block).split(b"\0")
            pending = pieces.pop()
            for piece in pieces:
                yield Path(os.fsdecode(piece))
        if process.wait():
            errors.seek(0, os.SEEK_END)
            errors.seek(max(0, errors.tell() - 65536))
            lines = os.fsdecode(errors.read()).strip().splitlines()
            raise OSError(f"fd failed: {lines[-1] if lines else 'unknown error'}")


def looks_machine_named(stem: str) -> bool:
    name = stem.lower()
    if name.startswith(_CAMERA_PREFIXES) or _ISO_DATE.fullmatch(name):
        return False
    return bool(
        re.fullmatch(r"[0-9a-f]{8,}([-_][0-9a-f]{4,})*", name)
        or re.fullmatch(r"[a-z]{0,16}[-_. ]?\d{3,}([-_.]\d+)*", name)
    )


def datasets(paths: Iterable[Path | str], *, root: Path) -> dict[Path, dict]:
    """Media folders that look generated: 300+ files of one media kind, 70%+ machine-named.

    Reads names only. `root` itself is never a dataset.
    """
    groups = defaultdict(lambda: [0, 0])
    root = str(root)
    for path in paths:
        name = str(path)
        parent = os.path.dirname(name) or '.'
        basename = os.path.basename(name)
        kind = classify_name(basename)
        if parent != root and kind in MEDIA_KINDS:
            stem = os.path.splitext(basename)[0]
            groups[parent, kind][0] += 1
            groups[parent, kind][1] += looks_machine_named(stem)
    return dataset_counts(groups)


def dataset_counts(groups: dict[tuple[str, str], list[int]]) -> dict[Path, dict]:
    """Dataset evidence from (folder, kind) -> [total, machine-named] tallies."""
    found = {}
    for (folder, kind), (total, named) in groups.items():
        if total >= 300 and named / total >= 0.7:
            found[Path(folder)] = {"kind": kind, "files": total,
                                   "named": round(100 * named / total)}
    return found


def keep(paths: Iterable[Path]) -> Iterator[Path | Skip]:
    for path in paths:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            continue
        cap = SIZE_CAPS.get(classify(path), 16) * 1024 * 1024
        yield Skip(path, "size-cap") if size > cap else path


def exclude_rel(root: Path, excluded: str) -> str | None:
    path = Path(excluded)
    if path.is_absolute():
        try:
            path = path.relative_to(root)
        except ValueError:
            return None
    return os.path.normpath(path.as_posix()).rstrip("/") if str(path) != "." else ""


def is_excluded(rel: str, excludes: Sequence[str]) -> bool:
    rel = os.path.normpath(rel).strip("/")
    return any(not e or rel == e or rel.startswith(e + "/")
               for e in (os.path.normpath(e).strip("/") if e not in ("", ".") else ""
                         for e in excludes))
