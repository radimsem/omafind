import os

import pytest
from omafindd.crawler import crawl
from omafindd.store import Store


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / 'docs'
    root.mkdir()
    store = Store(tmp_path / 'index/v.sqlite', volume='v', mount=root)
    yield root, store, [{'path': str(root)}]
    store.close()


def test_changed_new_missing(tree):
    from omafindd.reconcile import reconcile

    root, store, roots = tree
    for name in ('change.txt', 'gone.txt', 'keep.txt'):
        (root / name).write_text('fixture')
    crawl(store, roots)
    with store.db:
        store.db.execute("UPDATE files SET state='done'")
    (root / 'change.txt').write_text('changed fixture')
    (root / 'gone.txt').unlink()
    (root / 'new.txt').write_text('new')
    progress = []
    result = reconcile(store, roots, progress=lambda done, total: progress.append((done, total)))
    assert (len(result.queued), result.deleted, result.unchanged, result.moved) == (2, 1, 1, 0)
    assert progress[-1] == (4, 4)
    assert dict(store.db.execute('SELECT path,state FROM files')) == {
        'change.txt': 'pending', 'new.txt': 'pending', 'keep.txt': 'done'}


def test_unchanged_tree_not_requeued(tree):
    from omafindd.reconcile import reconcile

    root, store, roots = tree
    (root / 'keep.txt').write_text('fixture')
    crawl(store, roots)
    with store.db:
        store.db.execute("UPDATE files SET state='done'")
    before = list(map(tuple, store.db.execute('SELECT * FROM segments')))
    stat = (root / 'keep.txt').stat()
    os.utime(root / 'keep.txt', (stat.st_atime, stat.st_mtime + 0.0005))
    result = reconcile(store, roots)
    assert result.queued == [] and result.unchanged == 1
    assert list(map(tuple, store.db.execute('SELECT * FROM segments'))) == before


def test_inode_change_alone_is_not_a_change(tree):
    root, store, roots = tree
    (root / 'keep.txt').write_text('fixture')
    crawl(store, roots)
    before = list(map(tuple, store.db.execute('SELECT * FROM segments')))
    with store.db:
        store.db.execute("UPDATE files SET inode=inode+1,device=device+1,state='done'")
    assert crawl(store, roots) == []
    row = store.db.execute('SELECT inode,device,state FROM files').fetchone()
    stat = (root / 'keep.txt').stat()
    assert tuple(row) == (stat.st_ino, stat.st_dev, 'done')
    assert list(map(tuple, store.db.execute('SELECT * FROM segments'))) == before


def test_vanished_root_keeps_rows(tree):
    root, store, roots = tree
    (root / 'keep.txt').write_text('fixture')
    crawl(store, roots)
    root.rename(root.with_name('offline'))
    assert crawl(store, roots) == []
    assert store.db.execute('SELECT count(*) FROM files').fetchone()[0] == 1


def test_root_vanishing_mid_walk_keeps_rows(tree, monkeypatch):
    from omafindd import rules
    from omafindd.reconcile import reconcile

    root, store, roots = tree
    (root / 'keep.txt').write_text('fixture')
    crawl(store, roots)

    def vanished(*args, **kwargs):
        root.rename(root.with_name('offline'))
        yield from ()

    monkeypatch.setattr(rules, 'walk', vanished)
    assert reconcile(store, roots).deleted == 0
    assert store.db.execute('SELECT count(*) FROM files').fetchone()[0] == 1


def test_partial_reconcile_does_not_delete_neighbor(tree):
    from omafindd.reconcile import reconcile

    root, store, roots = tree
    for folder in ('one', 'other'):
        (root / folder).mkdir()
        (root / folder / 'note.txt').write_text('fixture')
    crawl(store, roots)
    (root / 'one/note.txt').unlink()
    assert reconcile(store, roots, only=[root / 'one']).deleted == 1
    assert store.db.execute('SELECT path FROM files').fetchone()[0] == 'other/note.txt'



def test_checked_dataset_is_queued_for_indexing(tree):
    from omafindd.reconcile import reconcile
    from omafindd.rules import datasets

    root, store, _ = tree
    folder = root / "frames"
    folder.mkdir()
    paths = [folder / f"frame_{n:06}.png" for n in range(300)]
    for path in paths:
        path.write_bytes(b"fixture")
    assert datasets(paths, root=root)[folder]["files"] == 300
    result = reconcile(store, [{"path": str(folder), "excludes": []}])
    assert len(result.queued) == 300
    assert store.db.execute("SELECT count(*) FROM files WHERE state='pending'").fetchone()[0] == 300
