import asyncio
import json
import logging
import re
import sqlite3
import subprocess
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from .store import _unescape_target

POLL_ARGV = ['findmnt', '--poll=mount,umount,move', '-P', '-o', 'ACTION,TARGET,SOURCE,FSTYPE,UUID']
LSBLK_ARGV = ['lsblk', '-J', '-b', '-o', 'UUID,LABEL,FSTYPE,SIZE,RM,HOTPLUG,MOUNTPOINTS']
_PSEUDO = {'tmpfs', 'devtmpfs', 'proc', 'sysfs', 'overlay', 'squashfs', 'cgroup', 'cgroup2',
           'devpts', 'securityfs', 'debugfs', 'tracefs', 'pstore', 'autofs', 'fusectl',
           'configfs', 'mqueue', 'hugetlbfs', 'bpf', 'ramfs', 'efivarfs'}
logger = logging.getLogger(__name__)
_ERRORS = (sqlite3.Error, OSError, subprocess.SubprocessError, ValueError)


@dataclass(frozen=True)
class Volume:
    uuid: str
    label: str
    fs: str
    size: int
    mount: Path | None
    removable: bool
    online: bool


@dataclass(frozen=True)
class MountEvent:
    action: str
    target: Path
    source: str
    fstype: str
    uuid: str | None


@dataclass(frozen=True)
class VolumeEvent:
    kind: Literal['appeared', 'returned', 'gone']
    volume: Volume


def parse_poll(line) -> MountEvent | None:
    if isinstance(line, bytes):
        line = line.decode(errors='replace')
    pairs = {key: _unescape_target(value) for key, value in re.findall(r'(\w+)="([^"]*)"', line)}
    if (pairs.get('ACTION') not in ('mount', 'umount', 'move')
        or not pairs.get('TARGET', '').startswith('/')):
        return None
    return MountEvent(pairs['ACTION'], Path(pairs['TARGET']), pairs.get('SOURCE', ''),
                      pairs.get('FSTYPE', ''), pairs.get('UUID') or None)


def _under(path, prefixes):
    return path is not None and any(path.is_relative_to(Path(prefix)) for prefix in prefixes)


def is_drive(event_or_volume) -> bool:
    path = (event_or_volume.target if isinstance(event_or_volume, MountEvent)
            else event_or_volume.mount)
    fs = (event_or_volume.fstype if isinstance(event_or_volume, MountEvent)
          else event_or_volume.fs)
    return fs not in _PSEUDO and _under(path, ('/run/media', '/media', '/mnt'))


def _size(value):
    # Old host fixtures were captured without lsblk -b.
    match = re.fullmatch(r'(\d+(?:\.\d+)?)([KMGTPE]?)', str(value or 0), re.IGNORECASE)
    if match is None:
        return 0
    return int(float(match[1]) * 1024 ** ('KMGTPE'.index(match[2].upper()) + 1 if match[2] else 0))


def parse_lsblk(data: dict) -> dict[str, Volume]:
    volumes = {}

    def visit(devices, removable=False):
        for device in devices:
            removable_here = (removable or device.get('rm') in (True, 1, '1')
                              or device.get('hotplug') in (True, 1, '1'))
            mounts = [Path(path) for path in device.get('mountpoints', []) if path]
            mount = next(
                (path for path in mounts if _under(path, ('/run/media', '/media', '/mnt'))),
                min(mounts, key=lambda path: len(str(path)), default=None))
            uuid = device.get('uuid')
            if uuid:
                label = device.get('label') or (mount.name if mount else '') or uuid
                volumes[uuid] = Volume(
                    uuid, label, device.get('fstype') or '', _size(device.get('size')),
                    mount, removable_here or _under(mount, ('/run/media', '/media')),
                    mount is not None)
            visit(device.get('children', []), removable_here)

    visit(data.get('blockdevices', []))
    return volumes


def lsblk() -> dict:
    result = subprocess.run(LSBLK_ARGV, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


class Volumes:
    def __init__(self, *, lsblk, known, ignored, clock=time.monotonic):
        self.lsblk, self.known, self.ignored, self.clock = lsblk, known, ignored, clock
        self._last, self._announced = {}, {}
        self._pending, self._events = [], []

    def snapshot(self) -> None:
        self._last.update(parse_lsblk(self.lsblk()))

    def online(self) -> dict[str, Volume]:
        return {uuid: volume for uuid, volume in self._last.items() if volume.online}

    def last(self, uuid) -> Volume | None:
        return self._last.get(uuid)

    def step(self, event: MountEvent) -> list[VolumeEvent]:
        try:
            return self._step(event)
        except _ERRORS as error:
            if event not in self._pending:
                self._pending.append(event)
            logger.warning('Volume facts failed (%s); retrying.', type(error).__name__)
            return []

    def _step(self, event: MountEvent) -> list[VolumeEvent]:
        if not is_drive(event):
            return []
        previous = self._last.get(event.uuid)
        if event.action == 'umount':
            if previous is None:
                previous = next((volume for volume in self._last.values()
                                 if volume.mount == event.target), None)
            if previous is None or not previous.online:
                return []
            known = self.known(previous.uuid)
            volume = replace(previous, mount=None, online=False)
            self._last[volume.uuid] = volume
            self._announced.pop(volume.uuid, None)
            return [VolumeEvent('gone', volume)] if known else []
        facts = parse_lsblk(self.lsblk())
        volume = facts.get(event.uuid) or next((volume for volume in facts.values()
                                              if volume.mount == event.target), None)
        if volume is None:
            if not event.uuid:
                return []
            volume = previous or Volume(event.uuid, event.target.name or event.uuid,
                                         event.fstype, 0, event.target, False, True)
        volume = replace(
            volume, mount=event.target, online=True,
            removable=volume.removable or _under(event.target, ('/run/media', '/media')))
        self._last[volume.uuid] = volume
        if self._announced.get(volume.uuid) == event.target:
            return []
        known, ignored = self.known(volume.uuid), self.ignored()
        self._announced[volume.uuid] = event.target
        if known:
            return [VolumeEvent('returned', volume)]
        return [] if volume.uuid in ignored else [VolumeEvent('appeared', volume)]

    async def run(self, on_events, *, spawn=asyncio.create_subprocess_exec, sleep=asyncio.sleep):
        failures = 0
        while True:
            process = None
            try:
                pending, self._pending = self._pending, []
                for event in pending:
                    self._events.extend(self.step(event))
                if self._events:
                    await on_events(list(self._events))
                    self._events.clear()
                if self._pending:
                    await sleep(min(0.5 * 2 ** min(failures, 6), 30))
                    failures += 1
                    continue
                process = await spawn(*POLL_ARGV, stdout=asyncio.subprocess.PIPE,
                                      stderr=asyncio.subprocess.DEVNULL)
                while line := await process.stdout.readline():
                    event = parse_poll(line)
                    if event is not None:
                        failures = 0
                        self._events.extend(self.step(event))
                        if self._events:
                            await on_events(list(self._events))
                            self._events.clear()
                        if self._pending:
                            break
                if not self._pending:
                    await process.wait()
            except _ERRORS as error:
                logger.warning('Volume polling failed (%s); retrying.', type(error).__name__)
            finally:
                if process is not None and process.returncode is None:
                    try:
                        process.terminate()
                        await process.wait()
                    except (OSError, subprocess.SubprocessError) as error:
                        logger.warning('Volume poll cleanup failed (%s)', type(error).__name__)
            await sleep(min(0.5 * 2 ** min(failures, 6), 30))
            failures += 1


def remap_root(root: dict, mounts: dict[str, Path], last_mounts: dict[str, Path]) -> dict | None:
    uuid = root.get('volume')
    mount = mounts.get(uuid)
    if mount is None:
        return None
    path = Path(root['path']).expanduser().absolute()
    last = last_mounts.get(uuid)
    mapped = dict(root)
    if last is not None and path.is_relative_to(last):
        mapped['path'] = str(mount / path.relative_to(last))
        mapped['excludes'] = [str(mount / Path(exclude).relative_to(last))
                              if Path(exclude).is_absolute() and Path(exclude).is_relative_to(last)
                              else exclude for exclude in root.get('excludes', [])]
    else:
        mapped['path'] = str(path)
    return mapped
