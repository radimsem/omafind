import os
import threading
import time

import pytest
from inotify_simple import flags
from omafindd.inotify import Event, InotifyObserver, Watch


def _inotify_fds():
    count = 0
    for name in os.listdir("/proc/self/fd"):
        try:
            if os.readlink(f"/proc/self/fd/{name}") == "anon_inode:inotify":
                count += 1
        except OSError:
            pass
    return count


class Recorder:
    def __init__(self):
        self.events = []
        self.seen = threading.Event()

    def on_any_event(self, event):
        self.events.append(event)
        self.seen.set()


def test_two_hundred_directories_share_one_instance_and_thread(tmp_path):
    folders = [tmp_path / f"d{n}" for n in range(200)]
    for folder in folders:
        folder.mkdir()
    fds, threads = _inotify_fds(), threading.active_count()
    observer = InotifyObserver()
    observer.start()
    try:
        for folder in folders:
            observer.schedule(Recorder(), str(folder))
        assert _inotify_fds() == fds + 1
        assert threading.active_count() == threads + 1
    finally:
        observer.stop()
        observer.join()
    assert _inotify_fds() == fds


def test_file_write_reaches_the_directory_handler(tmp_path):
    observer, recorder = InotifyObserver(), Recorder()
    observer.start()
    try:
        observer.schedule(recorder, str(tmp_path))
        (tmp_path / "note.txt").write_text("x")
        assert recorder.seen.wait(5)
        assert Event("created", str(tmp_path / "note.txt"), False) in recorder.events
    finally:
        observer.stop()
        observer.join()


def test_overflow_calls_on_overflow():
    observer = InotifyObserver()
    called = []
    observer.on_overflow = lambda: called.append(True)
    observer._dispatch(type("E", (), {"wd": -1, "mask": 0x4000, "cookie": 0, "name": ""})())
    assert called == [True]


def test_stale_watch_does_not_remove_reused_descriptor(tmp_path):
    observer = InotifyObserver()
    observer.start()
    try:
        first = tmp_path / "a"
        first.mkdir()
        old = observer.schedule(Recorder(), str(first))
        first.rmdir()
        deadline = time.monotonic() + 5
        while old.wd in observer._watches and time.monotonic() < deadline:
            time.sleep(0.01)
        second = tmp_path / "b"
        second.mkdir()
        new = observer.schedule(Recorder(), str(second))
        observer.unschedule(old)
        assert observer._watches[new.wd][1] == str(second)
    finally:
        observer.stop()
        observer.join()


@pytest.mark.parametrize("mask", [flags.DELETE_SELF, flags.MOVE_SELF])
def test_self_event_reports_the_watched_directory_as_deleted(tmp_path, mask):
    observer, recorder = InotifyObserver(), Recorder()
    observer._watches[1] = (recorder, str(tmp_path), Watch(1, str(tmp_path)))
    observer._dispatch(type("E", (), {"wd": 1, "mask": mask, "cookie": 0, "name": ""})())
    assert recorder.events == [Event("deleted", str(tmp_path), True)]


def test_stale_watch_does_not_remove_reused_descriptor_at_the_same_path(tmp_path):
    class Reusing:
        def __init__(self):
            self.removed = []

        def add_watch(self, path, mask):
            return 7

        def rm_watch(self, wd):
            self.removed.append(wd)

    backend = Reusing()
    observer = InotifyObserver(inotify_factory=lambda: backend)
    old = observer.schedule(Recorder(), str(tmp_path))
    observer._dispatch(type("E", (), {"wd": 7, "mask": flags.IGNORED})())
    new = observer.schedule(Recorder(), str(tmp_path))
    assert old.wd == new.wd
    observer.unschedule(old)
    assert observer._watches[new.wd][1] == str(tmp_path)
    assert backend.removed == []
    observer.unschedule(new)
    assert backend.removed == [7]


class Scripted:
    """An inotify backend whose read() returns or raises the queued results in order."""

    def __init__(self, *results):
        self.results = list(results)
        self.closed = 0

    def add_watch(self, path, mask):
        return 1

    def rm_watch(self, wd):
        pass

    def read(self, timeout=None):
        if not self.results:
            time.sleep(timeout / 1000)
            return []
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def close(self):
        self.closed += 1


def _event(name, mask=flags.CREATE):
    return type("E", (), {"wd": 1, "mask": mask, "cookie": 0, "name": name})()


def test_failing_handler_does_not_stop_the_reader(tmp_path):
    class Failing(Recorder):
        def on_any_event(self, event):
            if event.src_path.endswith("bad"):
                raise RuntimeError("Event loop is closed")
            super().on_any_event(event)

    recorder = Failing()
    observer = InotifyObserver(
        inotify_factory=lambda: Scripted([_event("bad")], [_event("good")]))
    observer.schedule(recorder, str(tmp_path))
    observer.start()
    try:
        assert recorder.seen.wait(5)
        assert recorder.events == [Event("created", str(tmp_path / "good"), False)]
    finally:
        observer.stop()
        observer.join()


def test_read_error_rebuilds_and_keeps_reading(tmp_path):
    recorder, overflowed = Recorder(), threading.Event()
    observer = InotifyObserver(
        inotify_factory=lambda: Scripted(OSError("read failed"), [_event("after")]))
    observer.retry_seconds = 0
    observer.on_overflow = overflowed.set
    observer.schedule(recorder, str(tmp_path))
    observer.start()
    try:
        assert overflowed.wait(5)
        assert recorder.seen.wait(5)
        assert recorder.events == [Event("created", str(tmp_path / "after"), False)]
    finally:
        observer.stop()
        observer.join()


def test_repeated_read_errors_back_off_until_a_read_succeeds(tmp_path):
    waits, settled = [], threading.Event()

    class Recording(threading.Event):
        def wait(self, timeout=None):
            if timeout is None:
                return super().wait()
            waits.append(timeout)
            if len(waits) == 3:
                settled.set()
            return self.is_set()

    error = OSError("read failed")
    observer = InotifyObserver(inotify_factory=lambda: Scripted(error, error, [], error))
    observer._stopped = Recording()
    observer.retry_seconds = 0.5
    observer.schedule(Recorder(), str(tmp_path))
    observer.start()
    try:
        assert settled.wait(5)
        assert waits == [0.5, 1.0, 0.5]
    finally:
        observer.stop()
        observer.join()


def test_unschedule_after_join_is_harmless(tmp_path):
    backend = Scripted()
    observer = InotifyObserver(inotify_factory=lambda: backend)
    watch = observer.schedule(Recorder(), str(tmp_path))
    observer.join()
    assert backend.closed == 1 and observer._watches == {}
    observer.unschedule(watch)
    observer._watches[watch.wd] = (Recorder(), str(tmp_path), watch)
    observer.unschedule(watch)


def test_attribute_change_is_a_modification(tmp_path):
    from omafindd.inotify import MASK

    assert MASK & flags.ATTRIB
    observer, recorder = InotifyObserver(), Recorder()
    observer._watches[1] = (recorder, str(tmp_path), Watch(1, str(tmp_path)))
    observer._dispatch(_event("note.txt", flags.ATTRIB))
    assert recorder.events == [Event("modified", str(tmp_path / "note.txt"), False)]
