import asyncio
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

from . import rules
from .inotify import InotifyObserver

logger = logging.getLogger(__name__)


class _Handler:
    def __init__(self, watcher):
        self.watcher = watcher

    def on_any_event(self, event):
        if event.event_type not in ('created', 'deleted', 'modified', 'moved', 'closed'):
            return
        self.watcher.notice(Path(event.src_path), event.is_directory)
        if event.is_directory and event.event_type in ('created', 'deleted', 'moved'):
            self.watcher.directory_event(Path(event.src_path), event.event_type != 'created')
        if getattr(event, 'dest_path', ''):
            self.watcher.notice(Path(event.dest_path), event.is_directory)
            if event.is_directory:
                self.watcher.directory_event(Path(event.dest_path), False)


class Watcher:
    def __init__(self, *, on_dirty, clock=time.monotonic, sleep=asyncio.sleep,
                 observer_factory=InotifyObserver, window=2.0):
        self.on_dirty, self.clock, self.sleep = on_dirty, clock, sleep
        self.observer = observer_factory()
        self.window = window
        self.roots, self.dirty = {}, {}
        self.loop = None
        self.started = self.stopped = False
        self.watches = {}
        self.unwatched = 0
        self._lock = threading.RLock()
        self._watch_lock = threading.RLock()
        self._directory_events = []
        self._overflow = False
        if hasattr(self.observer, 'on_overflow'):
            self.observer.on_overflow = self.overflow

    def watch(self, roots: list[dict]) -> None:
        if self.loop is None:
            self.loop = asyncio.get_running_loop()
        with self._watch_lock:
            self.observer.unschedule_all()
            self.watches.clear()
            self.unwatched = 0
            mapped = {Path(root['path']).expanduser().resolve(): root for root in roots}
            with self._lock:
                self.roots = mapped
                self.dirty = {root: dirs for root, dirs in self.dirty.items() if root in self.roots}
            if not self.started:
                try:
                    self.observer.start()
                    self.started = True
                except OSError:
                    self.observer.unschedule_all()
                    self.watches.clear()
                    raise
            for root in self.roots:
                self._add_tree(root)

    def _allowed(self, path, root):
        if rules.reason(path) is not None:
            return False
        excludes = [rel for excluded in self.roots[root].get('excludes', [])
                    if (rel := rules.exclude_rel(root, excluded)) is not None]
        return not rules.is_excluded(path.relative_to(root).as_posix(), excludes)

    def _add_tree(self, path):
        roots = [root for root in self.roots if path.is_relative_to(root)]
        if path.is_symlink() or not roots or not any(self._allowed(path, root) for root in roots):
            return

        failures = []

        def failed(error):
            self.unwatched += 1
            failures.append(error.errno)

        for folder, dirs, _ in os.walk(path, onerror=failed):
            directory = Path(folder)
            dirs[:] = [name for name in dirs if not (directory / name).is_symlink()
                       and any(self._allowed(directory / name, root) for root in roots)]
            if directory not in self.watches:
                try:
                    self.watches[directory] = self.observer.schedule(
                        _Handler(self), str(directory), recursive=False)
                except OSError as error:
                    failed(error)

        if failures:
            logger.warning('Watcher could not watch %d directories (errno=%s)',
                           len(failures), failures[0])

    def overflow(self) -> None:
        if self.loop is not None and not self.stopped:
            self.loop.call_soon_threadsafe(setattr, self, '_overflow', True)

    def directory_event(self, path, removed):
        if self.loop is not None and not self.stopped:
            self.loop.call_soon_threadsafe(
                self._directory_events.append, (path.absolute(), removed))

    def _update_directories(self, events):
        with self._watch_lock:
            for path, removed in events:
                if not removed:
                    self._add_tree(path)
                    continue
                for directory in list(self.watches):
                    if directory.is_relative_to(path):
                        try:
                            self.observer.unschedule(self.watches[directory])
                        except OSError as error:
                            logger.warning('Watcher directory errno=%s', error.errno)
                        del self.watches[directory]

    def notice(self, path: Path, is_dir: bool) -> None:
        if self.loop is not None and not self.stopped and rules.reason(path) is None:
            self.loop.call_soon_threadsafe(self._notice, path, is_dir, self.clock())

    def _notice(self, path, is_dir, seen):
        path = path.absolute()
        with self._lock:
            for root in self.roots:
                if path.is_relative_to(root) and self._allowed(path, root):
                    directory = path.parent if path != root else root
                    self.dirty.setdefault(root, {}).setdefault(directory, seen)

    async def flush(self) -> None:
        if self._overflow:
            self._overflow = False
            self._directory_events = []
            with self._lock:
                settings = list(self.roots.values())
            await asyncio.to_thread(self.watch, settings)
            for setting in settings:
                await self.on_dirty(setting, None)
        events, self._directory_events = self._directory_events, []
        if events:
            work = asyncio.create_task(asyncio.to_thread(self._update_directories, events))
            try:
                await asyncio.shield(work)
            except asyncio.CancelledError:
                await asyncio.gather(work, return_exceptions=True)
                raise
            except (sqlite3.Error, OSError):
                self._directory_events[:0] = events
                raise
        now = self.clock()
        ready = []
        with self._lock:
            for root, pending in list(self.dirty.items()):
                dirs = {path for path, seen in pending.items() if seen + self.window <= now}
                if dirs:
                    for path in dirs:
                        del pending[path]
                    ready.append((root, self.roots[root], dirs))
        for root, setting, dirs in ready:
            try:
                await self.on_dirty(setting, dirs)
            except (sqlite3.Error, OSError) as error:
                logger.warning('Watcher dirty failed (%s)', type(error).__name__)
                with self._lock:
                    if root in self.roots:
                        for path in dirs:
                            self.dirty.setdefault(root, {}).setdefault(path, now - self.window)

    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        try:
            while not self.stopped:
                await self.sleep(0.1)
                try:
                    await self.flush()
                except (sqlite3.Error, OSError) as error:
                    logger.warning('Watcher flush failed (%s)', type(error).__name__)
        finally:
            self.stop()

    def stop(self) -> None:
        self.stopped = True
        if self.started:
            self.observer.stop()
            self.observer.join()
            self.started = False
