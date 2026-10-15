import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from . import rules

KINDS = ('text', 'pdf', 'image', 'video', 'audio')
RATES = {
    'gpu': {'text': .07, 'pdf': .37, 'image': .14, 'video': 3.2, 'audio': 1.5, 'code': .042},
    'cpu': {'text': .13, 'pdf': .54, 'image': 1.36, 'video': 18., 'audio': 11.1, 'code': .084},
    'bytes': {'text': 11000, 'pdf': 48000, 'image': 7000, 'video': 40000,
              'audio': 12000, 'code': 10000},
}


def non_system_volumes(lsblk_json: dict) -> list[tuple[str, Path]]:
    def entries(devices):
        for device in devices:
            yield device
            yield from entries(device.get('children', []))

    devices = list(entries(lsblk_json.get('blockdevices', [])))
    system = {'/', '/boot', '/home', '[SWAP]'}
    for device in devices:
        mounts = device.get('mountpoints') or []
        if device.get('fstype') == 'btrfs' and '/' in mounts:
            system.update(m for m in mounts if m)
    volumes = []
    for device in devices:
        uuid = device.get('uuid')
        for mount in device.get('mountpoints') or []:
            if uuid and mount and mount != '[SWAP]' and (
                mount not in system or device.get('rm') or device.get('hotplug')
            ):
                item = (uuid, Path(mount))
                if item not in volumes:
                    volumes.append(item)
                break
    return volumes


def xdg_dirs(home: Path) -> dict[str, Path]:
    try:
        text = (home / '.config/user-dirs.dirs').read_text()
    except FileNotFoundError:
        return {}
    result = {}
    for name, value in re.findall(r'^XDG_(\w+)_DIR="([^"]*)"', text, re.MULTILINE):
        path = Path(value.replace('${HOME}', str(home)).replace('$HOME', str(home)))
        if path.is_absolute() and path != home:
            result[name] = path
    return result


# The six XDG folders the Folders step checks when it opens.
XDG_PICKS = ("DOCUMENTS", "PICTURES", "VIDEOS", "MUSIC", "DOWNLOAD", "DESKTOP")
LIMIT = 500


def _visible(entry) -> bool:
    try:
        entry.path.encode()
        return entry.is_dir(follow_symlinks=False) and rules.reason_name(entry.name) is None
    except (OSError, UnicodeEncodeError):
        return False


def _has_children(path) -> bool:
    try:
        with os.scandir(path) as entries:
            return any(_visible(entry) for entry in entries)
    except OSError:
        return False


def folders(path) -> list[dict]:
    """Child folders of `path` the tree shows, by name. Raises OSError when `path` is unreadable.

    Symlinks, hidden names, heavy and vendor names and secret names are left out.
    """
    with os.scandir(path) as entries:
        names = sorted((entry.path for entry in entries if _visible(entry)),
                       key=lambda name: (os.path.basename(name).casefold(), name))[:LIMIT]
    return [{"path": name, "name": os.path.basename(name),
             "repo": os.path.exists(os.path.join(name, ".git")), "hasChildren": _has_children(name)}
            for name in names]


def top(*, home: Path, volume: str | None = None, run=subprocess.run, lsblk=None, xdg=None,
        volume_of=None) -> dict:
    """The first level of the Folders step: one directory read per root.

    Without `volume` the roots are `home` and every mounted non-system volume; volumes outside
    `home` become extra rows. With `volume` the root is that volume's mount.
    """
    home = home.absolute()
    if lsblk is None:
        result = run(['lsblk', '-J', '-o', 'UUID,LABEL,FSTYPE,SIZE,RM,HOTPLUG,MOUNTPOINTS'],
                     capture_output=True, check=True)
        lsblk = json.loads(result.stdout)
    volumes = non_system_volumes(lsblk)
    if volume is not None:
        mount = next((path for uuid, path in volumes if uuid == volume), None)
        if mount is None:
            raise ValueError("That drive is not mounted. Plug it in and try again.")
        rows = [dict(row, xdg=False, volume=volume) for row in folders(mount)]
        return {"roots": [{"path": str(mount), "volume": volume}], "folders": rows}
    xdg = xdg_dirs(home) if xdg is None else xdg
    picks = {str(xdg[name]) for name in XDG_PICKS if name in xdg}
    lookup = _volume_lookup(lsblk) if volume_of is None else volume_of
    rows = [dict(row, xdg=row["path"] in picks) for row in folders(home)]
    roots = [{"path": str(home), "volume": lookup(home)[0]}]
    for uuid, mount in volumes:
        roots.append({"path": str(mount), "volume": uuid})
        if not mount.is_relative_to(home):
            rows.append({"path": str(mount), "name": str(mount),
                         "repo": os.path.exists(os.path.join(mount, ".git")), "hasChildren": True,
                         "xdg": False, "volume": uuid})
    for row in rows:
        row.setdefault("volume", lookup(Path(row["path"]))[0])
    return {"roots": roots, "folders": rows}


class Walk:
    """One fd pass over a root that rolls indexable file counts up to every folder above them.

    `run` blocks; the daemon calls it in a thread and reads `count`, `dataset` and `snapshot`
    from other threads, so shared state sits behind a lock.
    """

    def __init__(self, root, *, popen=subprocess.Popen, clock=time.monotonic):
        self.root = Path(root)
        self.popen, self.clock = popen, clock
        self.counts = {}
        self.datasets = []
        self.done = False
        self.seconds = None
        self.error = None
        self._stop = False
        self._process = None
        self._lock = threading.Lock()

    def stop(self):
        with self._lock:
            self._stop = True
            self._terminate()

    def _terminate(self):
        if self._process is not None:
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass

    def _popen(self, *args, **kwargs):
        with self._lock:
            self._process = self.popen(*args, **kwargs)
            if self._stop:
                self._terminate()
            return self._process

    def count(self, path):
        with self._lock:
            counts = self.counts.get(path)
            if counts is not None:
                return dict(counts)
            return dict.fromkeys((*KINDS, "dirs"), 0) if self.done else None

    def dataset(self, path):
        with self._lock:
            found = next((entry for entry in self.datasets if entry["path"] == path), None)
        return None if found is None else {k: v for k, v in found.items() if k != "path"}

    def snapshot(self):
        with self._lock:
            body = {"root": str(self.root),
                    "counts": {path: dict(counts) for path, counts in self.counts.items()},
                    "done": self.done, "seconds": self.seconds}
            if self.done:
                body["datasets"] = list(self.datasets)
            if self.error:
                body["error"] = self.error
        return body

    def _batch(self, changed):
        with self._lock:
            return {"root": str(self.root),
                    "counts": {path: dict(self.counts[path]) for path in changed},
                    "done": self.done, "seconds": self.seconds}

    def run(self, emit, *, every=.25):
        started = last = self.clock()
        root = str(self.root)
        changed, media = set(), {}
        listing = None
        try:
            listing = rules.walk(self.root, excludes=[], run=self._popen)
            for path in listing:
                if self._stop:
                    break
                name = str(path)
                try:
                    name.encode()
                except UnicodeEncodeError:
                    continue
                kind = rules.classify_name(os.path.basename(name))
                if kind is None:
                    continue
                folder = os.path.dirname(name)
                if kind in rules.MEDIA_KINDS and folder != root:
                    tally = media.setdefault((folder, kind), [0, 0])
                    tally[0] += 1
                    stem = os.path.splitext(os.path.basename(name))[0]
                    tally[1] += rules.looks_machine_named(stem)
                with self._lock:
                    new_dirs = 0
                    while True:
                        if folder not in self.counts:
                            new_dirs += 1
                        counts = self.counts.setdefault(folder, dict.fromkeys((*KINDS, "dirs"), 0))
                        counts[kind] += 1
                        counts["dirs"] += new_dirs
                        changed.add(folder)
                        if len(folder) <= len(root):
                            break
                        folder = os.path.dirname(folder)
                now = self.clock()
                if now - last >= every:
                    emit(self._batch(changed))
                    changed, last = set(), now
        except OSError as error:
            if not self._stop:
                self.error = str(error) or type(error).__name__
        finally:
            if listing is not None:
                listing.close()
            with self._lock:
                self._process = None
        found = rules.dataset_counts(media)
        with self._lock:
            self.datasets = [{"path": str(path), **evidence}
                             for path, evidence in sorted(found.items())]
            self.done = True
            self.seconds = round(float(self.clock() - started), 1)
        batch = self._batch(changed)
        batch["datasets"] = list(self.datasets)
        if self.error:
            batch["error"] = self.error
        emit(batch)


def children(path, walk=None) -> dict:
    """One level under `path`. Counts come from `walk`, null until the walk reaches a folder."""
    try:
        rows = folders(path)
    except OSError as error:
        return {"path": str(path), "dirs": [], "error": error.strerror or str(error)}
    for row in rows:
        row["counts"] = walk.count(row["path"]) if walk is not None else None
        row["evidence"] = walk.dataset(row["path"]) if walk is not None else None
        row["rule"] = "dataset" if row["evidence"] else None
    rows.sort(key=lambda row: (-sum((row["counts"] or {}).get(kind, 0) for kind in KINDS),
                               row["name"].casefold()))
    return {"path": str(path), "dirs": rows, "error": None}


def snapshot(*, home: Path, volume: str | None = None) -> dict:
    """The `discover --json` body: what `discover_start` replies, without walking."""
    return {"home": str(home.absolute()), "device": device(home), "rates": RATES,
            **top(home=home, volume=volume)}


def device(home):
    from .embedder import free_vram
    from .settings import load

    settings = load(home / '.config/omarchy/shell.json')
    if settings.gpu == 'never':
        return 'cpu'
    free = free_vram()
    return 'cpu' if free is not None and free < 1536 else 'gpu'


def _volume_of(path):
    from .store import volume_for

    return volume_for(path)


def _volume_lookup(lsblk):
    from .store import mounted_volumes

    mounts = {mount: uuid for uuid, mount in mounted_volumes().items()}

    def collect(devices):
        for device in devices:
            if device.get('uuid'):
                for mount in device.get('mountpoints') or []:
                    if mount and mount.startswith('/'):
                        mounts[Path(mount)] = device['uuid']
            collect(device.get('children', []))

    collect(lsblk.get('blockdevices', []))
    ordered = sorted(mounts, key=lambda p: len(p.parts), reverse=True)

    def lookup(path):
        for mount in ordered:
            if path.is_relative_to(mount):
                return mounts[mount], mount
        return _volume_of(path)

    return lookup


def _expand(path, home):
    if path == '~':
        return home
    return Path(os.path.abspath(home / path[2:] if path.startswith('~/') else path))


def list_dirs(path: str, *, home: Path) -> dict:
    absolute = _expand(path, home)
    result = {'path': path, 'abs': str(absolute), 'dirs': [], 'error': None}
    try:
        with os.scandir(absolute) as entries:
            result['dirs'] = sorted((entry.name for entry in entries
                                     if not entry.name.startswith('.')
                                     and entry.name not in rules.HEAVY_GLOBS
                                     and entry.is_dir()), key=lambda n: (n.casefold(), n))[:500]
    except FileNotFoundError:
        result['error'] = 'missing'
    except NotADirectoryError:
        result['error'] = 'not-a-directory'
    except PermissionError:
        result['error'] = 'denied'
    return result
