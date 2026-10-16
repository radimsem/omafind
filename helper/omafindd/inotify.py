"""One inotify instance for every watched directory, read by one thread."""

import errno
import logging
import os
import threading
from dataclasses import dataclass

from inotify_simple import INotify, flags

logger = logging.getLogger(__name__)

MASK = (flags.CREATE | flags.DELETE | flags.MODIFY | flags.ATTRIB | flags.MOVED_FROM
        | flags.MOVED_TO | flags.CLOSE_WRITE | flags.DELETE_SELF | flags.MOVE_SELF
        | flags.ONLYDIR)


@dataclass(frozen=True)
class Event:
    event_type: str
    src_path: str
    is_directory: bool
    dest_path: str = ""


@dataclass(frozen=True)
class Watch:
    wd: int
    path: str


def _event_type(mask):
    if mask & (flags.CREATE | flags.MOVED_TO):
        return "created"
    if mask & (flags.DELETE | flags.MOVED_FROM):
        return "deleted"
    if mask & flags.CLOSE_WRITE:
        return "closed"
    if mask & (flags.MODIFY | flags.ATTRIB):
        return "modified"
    return None


class InotifyObserver:
    """Directory watches on a single inotify fd."""

    def __init__(self, *, inotify_factory=INotify):
        self._factory = inotify_factory
        self._inotify = None
        self._watches = {}
        self._lock = threading.Lock()
        self._thread = None
        self._stopped = threading.Event()
        self.on_overflow = lambda: None
        self.retry_seconds = 1.0

    def _ensure(self):
        if self._inotify is None:
            self._inotify = self._factory()
        return self._inotify

    def start(self):
        self._ensure()
        self._stopped.clear()
        self._thread = threading.Thread(target=self._run, name="omafind-inotify", daemon=True)
        self._thread.start()

    def schedule(self, handler, path, *, recursive=False):
        with self._lock:
            wd = self._ensure().add_watch(path, MASK)
            watch = Watch(wd, path)
            self._watches[wd] = (handler, path, watch)
        return watch

    def unschedule(self, watch):
        with self._lock:
            entry = self._watches.get(watch.wd)
            # inotify can reuse both the descriptor and path after IN_IGNORED.
            if entry is None or entry[2] is not watch:
                return
            del self._watches[watch.wd]
            if self._inotify is None:
                return
            try:
                self._inotify.rm_watch(watch.wd)
            except OSError as error:
                if error.errno != errno.EINVAL:
                    raise

    def unschedule_all(self):
        with self._lock:
            watches = [entry[2] for entry in self._watches.values()]
        for watch in watches:
            self.unschedule(watch)

    def stop(self):
        self._stopped.set()

    def join(self):
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        with self._lock:
            if self._inotify is not None:
                self._inotify.close()
                self._inotify = None
            self._watches.clear()

    def _run(self):
        delay = self.retry_seconds
        while not self._stopped.is_set():
            try:
                events = self._inotify.read(timeout=250)
            except OSError:
                if self._stopped.is_set():
                    return
                logger.exception("inotify read failed, rescanning the watched folders")
                self._call(self.on_overflow)
                self._stopped.wait(delay)
                # Every rescan walks all roots, so a lasting fault backs off to one a minute.
                delay = min(delay * 2, 60.0)
                continue
            delay = self.retry_seconds
            for event in events:
                self._call(self._dispatch, event)

    def _call(self, function, *args):
        # One failing handler must not end the thread that serves every watch.
        try:
            function(*args)
        except Exception:
            logger.exception("inotify event handling failed")

    def _dispatch(self, event):
        if event.mask & flags.Q_OVERFLOW:
            self.on_overflow()
            return
        with self._lock:
            if event.mask & flags.IGNORED:
                self._watches.pop(event.wd, None)
                return
            entry = self._watches.get(event.wd)
        if entry is None:
            return
        handler, directory, _ = entry
        if event.mask & (flags.DELETE_SELF | flags.MOVE_SELF):
            handler.on_any_event(Event("deleted", directory, True))
            return
        kind = _event_type(event.mask)
        if kind is None or not event.name:
            return
        handler.on_any_event(Event(kind, os.path.join(directory, event.name),
                                   bool(event.mask & flags.ISDIR)))
