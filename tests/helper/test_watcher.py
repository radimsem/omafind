import asyncio
import subprocess

import pytest
from omafindd.crawler import crawl
from omafindd.store import Store


class Observer:
    def __init__(self):
        self.watches = []
        self.started = self.stopped = False

    def unschedule_all(self):
        self.watches.clear()

    def schedule(self, handler, path, *, recursive):
        self.watches.append((handler, path, recursive))
        return path

    def unschedule(self, watch):
        self.watches = [item for item in self.watches if item[1] != watch]

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def join(self):
        pass


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / 'docs'
    root.mkdir()
    store = Store(tmp_path / 'index/v.sqlite', volume='v', mount=root)
    yield root, store
    store.close()


async def watcher_for(root, store):
    from omafindd.reconcile import reconcile
    from omafindd.watcher import Watcher

    now, results = [0.0], []

    async def dirty(setting, dirs):
        results.append(reconcile(store, [setting], only=dirs))

    observer = Observer()
    watcher = Watcher(on_dirty=dirty, clock=lambda: now[0], observer_factory=lambda: observer)
    watcher.watch([{'path': str(root)}])
    assert observer.watches[0][1:] == (str(root), False)
    return watcher, now, results


async def test_burst_of_50_writes_gives_one_pending_mark_after_2s(tree):
    root, store = tree
    path = root / 'note.txt'
    path.write_text('old')
    crawl(store, [{'path': str(root)}])
    with store.db:
        store.db.execute("UPDATE files SET state='done'")
    watcher, now, results = await watcher_for(root, store)
    try:
        for number in range(50):
            path.write_text(str(number))
            watcher.notice(path, False)
            now[0] += 0.02
        await asyncio.sleep(0)
        await watcher.flush()
        assert results == []
        now[0] = 2.0
        await watcher.flush()
        await watcher.flush()
        assert len(results) == 1 and len(results[0].queued) == 1
        assert store.db.execute('SELECT state FROM files').fetchone()[0] == 'pending'
    finally:
        watcher.stop()


async def test_delete_removes_segments(tree):
    root, store = tree
    path = root / 'note.txt'
    path.write_text('fixture')
    crawl(store, [{'path': str(root)}])
    watcher, now, results = await watcher_for(root, store)
    try:
        path.unlink()
        watcher.notice(path, False)
        await asyncio.sleep(0)
        now[0] = 2
        await watcher.flush()
        assert results[0].deleted == 1
        assert store.db.execute('SELECT count(*) FROM segments').fetchone()[0] == 0
        assert store.db.execute('SELECT count(*) FROM fts').fetchone()[0] == 0
    finally:
        watcher.stop()


async def test_id_rsa_never_gets_a_row(tree):
    root, store = tree
    watcher, now, results = await watcher_for(root, store)
    try:
        path = root / 'id_rsa.txt'
        path.write_text('invented fixture')
        watcher.notice(path, False)
        watcher.notice(root / 'ordinary.txt', False)
        await asyncio.sleep(0)
        now[0] = 2
        await watcher.flush()
        assert store.db.execute('SELECT count(*) FROM files').fetchone()[0] == 0
    finally:
        watcher.stop()


async def test_dir_ignored_by_parent_gitignore_gets_no_row_after_relist(tree):
    root, store = tree
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    (root / '.gitignore').write_text('ignored/\n')
    (root / 'ignored').mkdir()
    path = root / 'ignored/note.txt'
    path.write_text('fixture')
    watcher, now, results = await watcher_for(root, store)
    try:
        watcher.notice(path, False)
        await asyncio.sleep(0)
        now[0] = 2
        await watcher.flush()
        assert len(results) == 1
        assert store.db.execute('SELECT count(*) FROM files').fetchone()[0] == 0
    finally:
        watcher.stop()


async def test_excluded_directories_never_get_a_watch(tree):
    from omafindd.watcher import Watcher

    root, _ = tree
    for name in ('.hidden', 'node_modules', 'secret-folder', 'private', 'public'):
        (root / name / 'nested').mkdir(parents=True)
    observer = Observer()
    watcher = Watcher(on_dirty=None, observer_factory=lambda: observer)
    try:
        watcher.watch([{'path': str(root), 'excludes': [str(root / 'private')]}])
        assert {item[1] for item in observer.watches} == {
            str(root), str(root / 'public'), str(root / 'public/nested')}
        assert all(not item[2] for item in observer.watches)
    finally:
        watcher.stop()


async def test_created_subdirectory_gets_watch_and_deleted_watches_are_removed(tree, monkeypatch):
    from omafindd.inotify import Event

    root, store = tree
    async def inline(callback, *args):
        return callback(*args)

    monkeypatch.setattr(asyncio, 'to_thread', inline)
    watcher, _, _ = await watcher_for(root, store)
    try:
        handler = watcher.observer.watches[0][0]
        folder = root / 'new/nested'
        folder.mkdir(parents=True)
        handler.on_any_event(Event('created', str(root / 'new'), True))
        await asyncio.sleep(0)
        await watcher.flush()
        assert {item[1] for item in watcher.observer.watches} == {
            str(root), str(root / 'new'), str(folder)}
        folder.rmdir()
        folder.parent.rmdir()
        handler.on_any_event(Event('deleted', str(root / 'new'), True))
        await asyncio.sleep(0)
        await watcher.flush()
        assert [item[1] for item in watcher.observer.watches] == [str(root)]
    finally:
        watcher.stop()


async def test_enospc_on_one_directory_does_not_fail_root(tree, caplog):
    import errno

    from omafindd.watcher import Watcher

    root, _ = tree
    for name in ('full', 'okay'):
        (root / name).mkdir()

    class Full(Observer):
        def schedule(self, handler, path, *, recursive):
            if path == str(root / 'full'):
                raise OSError(errno.ENOSPC, 'private fixture text', path)
            return super().schedule(handler, path, recursive=recursive)

    observer = Full()
    watcher = Watcher(on_dirty=None, observer_factory=lambda: observer)
    try:
        watcher.watch([{'path': str(root)}])
        assert {item[1] for item in observer.watches} == {str(root), str(root / 'okay')}
        assert watcher.unwatched == 1
        assert str(root) not in caplog.text and 'private fixture text' not in caplog.text
    finally:
        watcher.stop()


async def test_overflow_marks_every_root_dirty(tree, monkeypatch):
    from omafindd.watcher import Watcher

    root, _ = tree
    calls = []

    async def dirty(setting, dirs):
        calls.append((setting['path'], dirs))

    async def inline(callback, *args):
        return callback(*args)

    monkeypatch.setattr(asyncio, 'to_thread', inline)
    watcher = Watcher(on_dirty=dirty, observer_factory=Observer)
    watcher.watch([{'path': str(root)}])
    try:
        watcher.overflow()
        await asyncio.sleep(0)
        await watcher.flush()
        assert calls == [(str(root), None)]
    finally:
        watcher.stop()


async def test_enospc_logs_one_line_for_many_directories(tree, caplog):
    import errno

    from omafindd.watcher import Watcher

    root, _ = tree
    for n in range(5):
        (root / f'full{n}').mkdir()

    class Full(Observer):
        def schedule(self, handler, path, *, recursive):
            if path != str(root):
                raise OSError(errno.ENOSPC, 'no space', path)
            return super().schedule(handler, path, recursive=recursive)

    watcher = Watcher(on_dirty=None, observer_factory=Full)
    try:
        watcher.watch([{'path': str(root)}])
        assert watcher.unwatched == 5
        assert caplog.text.count('Watcher') == 1
    finally:
        watcher.stop()


async def test_renamed_directory_moves_its_watches(tree, monkeypatch):
    from omafindd.inotify import Event

    root, store = tree

    async def inline(callback, *args):
        return callback(*args)

    monkeypatch.setattr(asyncio, 'to_thread', inline)
    (root / 'old/nested').mkdir(parents=True)
    watcher, _, _ = await watcher_for(root, store)
    try:
        handler = watcher.observer.watches[0][0]
        (root / 'old').rename(root / 'new')
        handler.on_any_event(Event('deleted', str(root / 'old'), True))
        handler.on_any_event(Event('created', str(root / 'new'), True))
        await asyncio.sleep(0)
        await watcher.flush()
        assert {item[1] for item in watcher.observer.watches} == {
            str(root), str(root / 'new'), str(root / 'new/nested')}
    finally:
        watcher.stop()


async def test_overflow_rebuilds_watches_for_missed_directory_events(tree, monkeypatch):
    from omafindd.watcher import Watcher

    root, _ = tree
    (root / 'old').mkdir()
    calls = []

    async def inline(callback, *args):
        return callback(*args)

    async def dirty(setting, dirs):
        calls.append((setting['path'], dirs))

    monkeypatch.setattr(asyncio, 'to_thread', inline)
    watcher = Watcher(on_dirty=dirty, observer_factory=Observer)
    watcher.watch([{'path': str(root)}])
    try:
        (root / 'old').rmdir()
        (root / 'new/nested').mkdir(parents=True)
        watcher.overflow()
        await asyncio.sleep(0)
        await watcher.flush()
        assert {item[1] for item in watcher.observer.watches} == {
            str(root), str(root / 'new'), str(root / 'new/nested')}
        assert calls == [(str(root), None)]
    finally:
        watcher.stop()


async def test_overflow_discards_stale_directory_events(tree, monkeypatch):
    from omafindd.inotify import Event

    root, store = tree

    async def inline(callback, *args):
        return callback(*args)

    monkeypatch.setattr(asyncio, 'to_thread', inline)
    folder = root / 'recreated'
    folder.mkdir()
    watcher, _, _ = await watcher_for(root, store)
    try:
        folder.rmdir()
        watcher.observer.watches[0][0].on_any_event(Event('deleted', str(folder), True))
        folder.mkdir()
        watcher.overflow()
        await asyncio.sleep(0)
        await watcher.flush()
        assert {item[1] for item in watcher.observer.watches} == {str(root), str(folder)}
    finally:
        watcher.stop()
