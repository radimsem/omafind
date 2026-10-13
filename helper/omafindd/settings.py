import json
import logging
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import health, paths

logger = logging.getLogger(__name__)


class _MissingEntry(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    setup_done: bool = False
    gpu: str = "auto"
    audio: bool = True
    roots: list[dict] = field(default_factory=list)
    max_results: int = 40
    warm_minutes: int = 5
    code_roots: tuple[str, ...] = ()
    image_budget: int = 140
    shortcut: str = "SUPER + E"
    ignored_volumes: tuple[str, ...] = ()


def valid_shortcut(value) -> bool:
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:SUPER|SHIFT|CTRL|ALT)(?:\s*\+\s*(?:SUPER|SHIFT|CTRL|ALT))*"
        r"\s*\+\s*[A-Z0-9_]+", value
    ):
        return False
    parts = [part.strip() for part in value.split("+")]
    return len(set(parts)) == len(parts) and parts[-1] not in ("SUPER", "SHIFT", "CTRL", "ALT")


def find_entry(config: dict, plugin_id: str) -> dict | None:
    bar = config.get("bar")
    layout = bar.get("layout") if isinstance(bar, dict) else None
    sections = ([layout.get(name) for name in ("left", "center", "right")]
                if isinstance(layout, dict) else [])
    for entries in [*sections, config.get("plugins")]:
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and entry.get("id") == plugin_id:
                return entry
    return None


def roots(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [{"path": root["path"], "volume": root["volume"], "excludes": root["excludes"][:]}
            for root in value if isinstance(root, dict)
            and isinstance(root.get("path"), str) and Path(root["path"]).is_absolute()
            and isinstance(root.get("volume"), str) and isinstance(root.get("excludes"), list)
            and all(isinstance(path, str) for path in root["excludes"])]


def _integer(entry, key, default, minimum, maximum):
    value = entry.get(key, default)
    return max(minimum, min(maximum, value)) if type(value) is int else default


def _load(path: Path) -> Settings:
    config = json.loads(path.read_text())
    entry = find_entry(config, "radimsem.omafind") if isinstance(config, dict) else None
    if entry is None:
        raise _MissingEntry("No omafind settings entry")
    setup_done = entry.get("setupDone", False)
    gpu = entry.get("gpu", "auto")
    audio = entry.get("audio", True)
    repositories = entry.get("codeRoots", [])
    ignored = entry.get("ignoredVolumes", [])
    budget = entry.get("imageBudget", 140)
    shortcut = entry.get("shortcut", "SUPER + E")
    return Settings(
        setup_done=setup_done if type(setup_done) is bool else False,
        gpu=gpu if gpu in ("auto", "never") else "auto",
        audio=audio if type(audio) is bool else True,
        roots=roots(entry.get("roots")),
        max_results=_integer(entry, "maxResults", 40, 10, 200),
        warm_minutes=_integer(entry, "warmMinutes", 5, 0, 60),
        code_roots=tuple(path for path in repositories
                         if isinstance(path, str) and Path(path).is_absolute())
        if isinstance(repositories, list) else (),
        image_budget=budget if type(budget) is int and budget in (70, 140, 280) else 140,
        shortcut=shortcut if valid_shortcut(shortcut) else "SUPER + E",
        ignored_volumes=tuple(uuid for uuid in ignored if isinstance(uuid, str) and uuid)
        if isinstance(ignored, list) else (),
    )


def _remap(settings, mounts=None):
    if not settings.roots:
        return settings
    if mounts is None:
        mounts = health.read(paths.health_path()).get("mounts", {})
    if not mounts:
        return settings
    mapped = []
    for root in settings.roots:
        mapping = mounts.get(root["volume"], {})
        current = mapping.get("current")
        path = Path(root["path"])
        changed = dict(root)
        if current and not path.is_relative_to(Path(current)):
            for previous in sorted(mapping.get("previous", []), key=len, reverse=True):
                old = Path(previous)
                if path.is_relative_to(old):
                    changed["path"] = str(Path(current) / path.relative_to(old))
                    changed["excludes"] = [
                        str(Path(current) / Path(exclude).relative_to(old))
                        if Path(exclude).is_absolute() and Path(exclude).is_relative_to(old)
                        else exclude for exclude in root["excludes"]]
                    break
        mapped.append(changed)
    return replace(settings, roots=mapped) if mapped != settings.roots else settings


def load(path: Path) -> Settings:
    try:
        return _remap(_load(path))
    except (OSError, ValueError, UnicodeError):
        logger.warning("Cannot read %s. Using default omafind settings.", path)
        return Settings()


class SettingsReader:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._signature = None
        self._settings = Settings()
        self._mapped = self._settings
        self._health_signature = None
        self._mounts = {}

    def read(self) -> Settings:
        try:
            stat = self.path.stat()
            signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino, stat.st_ctime_ns)
        except OSError:
            self._signature = None
            self._settings = Settings()
            self._mapped = self._settings
            return self._mapped
        if signature != self._signature:
            self._signature = signature
            try:
                self._settings = _load(self.path)
            except _MissingEntry:
                logger.warning("No radimsem.omafind entry in %s. Using default omafind settings.",
                               self.path)
            except (OSError, ValueError, UnicodeError):
                logger.warning("Cannot read %s. Keeping the last good omafind settings.", self.path)
        health_path = paths.health_path()
        try:
            info = health_path.stat()
            health_signature = (info.st_mtime_ns, info.st_size, info.st_ino)
        except OSError:
            health_signature = None
        if health_signature != self._health_signature:
            self._health_signature = health_signature
            self._mounts = health.read(health_path).get("mounts", {})
        mapped = _remap(self._settings, self._mounts)
        if mapped != self._mapped:
            self._mapped = mapped
        return self._mapped
