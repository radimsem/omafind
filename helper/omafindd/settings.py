import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

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
    return Settings(
        setup_done=setup_done if type(setup_done) is bool else False,
        gpu=gpu if gpu in ("auto", "never") else "auto",
        audio=audio if type(audio) is bool else True,
        roots=roots(entry.get("roots")),
        max_results=_integer(entry, "maxResults", 40, 10, 200),
        warm_minutes=_integer(entry, "warmMinutes", 5, 0, 60),
    )


def load(path: Path) -> Settings:
    try:
        return _load(path)
    except (OSError, ValueError, UnicodeError):
        logger.warning("Cannot read %s. Using default omafind settings.", path)
        return Settings()


class SettingsReader:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._signature = None
        self._settings = Settings()

    def read(self) -> Settings:
        try:
            stat = self.path.stat()
            signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino, stat.st_ctime_ns)
        except OSError:
            self._signature = None
            self._settings = Settings()
            return self._settings
        if signature != self._signature:
            self._signature = signature
            try:
                self._settings = _load(self.path)
            except _MissingEntry:
                logger.warning("No radimsem.omafind entry in %s. Using default omafind settings.",
                               self.path)
            except (OSError, ValueError, UnicodeError):
                logger.warning("Cannot read %s. Keeping the last good omafind settings.", self.path)
        return self._settings
