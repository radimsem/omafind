import fnmatch
import os
import re
import subprocess
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


def fd_args(root: Path, *, excludes: Sequence[str], kinds: Iterable[str]) -> list[str]:
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


def datasets(paths: Iterable[Path | str], *, root: Path) -> set[Path]:
    groups = defaultdict(list)
    root = str(root)
    for path in paths:
        name = str(path)
        parent = os.path.dirname(name) or '.'
        if parent != root:
            basename = os.path.basename(name)
            stem, suffix = os.path.splitext(basename)
            groups[parent, classify_name(basename)].append(basename if suffix == '.' else stem)
    return {
        Path(folder)
        for (folder, _), stems in groups.items()
        if len(stems) >= 300 and sum(map(looks_machine_named, stems)) / len(stems) >= 0.7
    }


def keep(paths: Iterable[Path], *, root: Path) -> Iterator[Path | Skip]:
    paths = list(paths)
    skipped = datasets(paths, root=root)
    for path in paths:
        if any(folder == path.parent or folder in path.parents for folder in skipped):
            yield Skip(path, "dataset")
            continue
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


def removed(root: Path, rule: str, *, run=subprocess.run, as_paths=True, baseline=None) -> set:
    args = fd_args(root, excludes=[], kinds=INDEXED_KINDS)

    def listing(argv):
        result = run(argv, cwd=root, capture_output=True, check=True)
        names = {os.fsdecode(p) for p in result.stdout.split(b"\0") if p}
        return {Path(name) for name in names} if as_paths else names

    baseline = listing(args) if baseline is None else set(baseline)
    if rule == "dot":
        return listing([args[0], "-H", *args[1:]]) - baseline
    globs = {"heavy": HEAVY_GLOBS, "secrets": SECRET_GLOBS}[rule]
    relaxed = []
    index = 0
    while index < len(args):
        if args[index] == "-E" and args[index + 1] in globs:
            index += 2
        else:
            relaxed.append(args[index])
            index += 1
    return listing(relaxed) - baseline


def explain(root: Path, *, run=subprocess.run) -> dict[str, int]:
    return {rule: len(removed(root, rule, run=run)) for rule in ("dot", "heavy", "secrets")}


def rule_dirs(paths: Iterable[Path], rule: str, *, root: Path) -> int:
    triggered = set()
    prefix = str(root).rstrip('/') + '/'
    heavy = set(HEAVY_GLOBS)
    for path in paths:
        name = str(path)
        rel = name[len(prefix):] if name.startswith(prefix) else os.path.relpath(name, root)
        parts = rel.split('/')[:-1]
        for index, part in enumerate(parts):
            if (rule == "dot" and part.startswith(".")) or (rule == "heavy" and part in heavy):
                triggered.add('/'.join(parts[:index + 1]))
                break
    return len(triggered)


def secret_family(name: str) -> str:
    lower = name.lower()
    for prefix in _SECRET_PREFIXES:
        if lower.startswith(prefix):
            return prefix
    for ext in _SECRET_TYPES:
        if lower.endswith("." + ext):
            return "." + ext
    return name
