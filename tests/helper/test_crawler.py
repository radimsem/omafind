import json
import os
import random
from collections import Counter
from concurrent.futures import Future

import pytest
from fakes.embedder import FakeEmbedder
from omafindd import crawler, indexing, rules
from omafindd.selection import FolderSelection, to_roots
from omafindd.store import Store


def write(root, names):
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('A useful note about architecture.')


def paths(store):
    return {r['path'] for r in store.db.execute('SELECT path FROM files')}


def test_file_under_an_exclude_gets_no_files_row(tmp_path):
    write(tmp_path, ['out/a.md', 'yes.md'])
    store = Store(tmp_path / 'index.sqlite', volume='test', mount=tmp_path)
    try:
        crawler.crawl(store, [{'path': str(tmp_path), 'excludes': ['out']}])
        assert paths(store) == {'yes.md'}
    finally:
        store.close()


def test_adding_an_exclude_later_deletes_that_subtree_rows(tmp_path):
    write(tmp_path, ['out/a.md', 'yes.md'])
    store = Store(tmp_path / 'index.sqlite', volume='test', mount=tmp_path)
    try:
        crawler.crawl(store, [{'path': str(tmp_path)}])
        assert paths(store) == {'out/a.md', 'yes.md'}
        crawler.crawl(store, [{'path': str(tmp_path), 'excludes': ['out']}])
        assert paths(store) == {'yes.md'}
    finally:
        store.close()


def test_relative_and_absolute_excludes_match_the_same_files(tmp_path):
    write(tmp_path, ['out/a.md', 'yes.md'])
    assert set(rules.walk(tmp_path, excludes=['out'])) == set(
        rules.walk(tmp_path, excludes=[str(tmp_path / 'out')])) == {tmp_path / 'yes.md'}


@pytest.mark.parametrize('folder', ['a[1]', 'a*', 'a?', 'a{b}', 'a]'])
def test_exclude_with_glob_characters_is_literal(tmp_path, folder):
    write(tmp_path, [f'{folder}/a.md', 'a1/a.md', f'nested/{folder}/a.md'])
    assert set(rules.walk(tmp_path, excludes=[folder])) == {
        tmp_path / 'a1/a.md', tmp_path / f'nested/{folder}/a.md'}


def test_python_exclude_predicate_matches_fd(tmp_path):
    names = [f'{folder}/{n}.md' for folder in ('a', 'a/b', 'a/b/c', 'ab', 'a[1]', 'c')
             for n in range(3)]
    write(tmp_path, names)
    rng = random.Random(5)
    for _ in range(20):
        excludes = rng.sample(['a', 'a/b', 'ab', 'a[1]', 'c'], rng.randrange(6))
        found = {str(p.relative_to(tmp_path)) for p in rules.walk(tmp_path, excludes=excludes)}
        assert found == {n for n in names if not rules.is_excluded(n, excludes)}


@pytest.mark.parametrize('folder', ['Upper', 'a[1]', 'a+b', 'a#b', 'a&b', 'a-b', 'a~b'])
def test_partial_walk_matches_literal_resolved_directory(tmp_path, folder):
    write(tmp_path, [f'{folder}/note.md', 'neighbor/note.md'])
    assert list(rules.walk(tmp_path, excludes=[], only=[tmp_path / folder / '..' / folder])) == [
        tmp_path / folder / 'note.md']


def test_chosen_folder_inside_skipped_one_is_walked(tmp_path):
    write(tmp_path, ['D/top.txt', 'D/Media/film.txt', 'D/Media/Courses/week1.txt',
                     'D/Media/Courses/Old/old.txt'])
    s = FolderSelection(chosen=[str(tmp_path / 'D'), str(tmp_path / 'D/Media/Courses')],
                        skipped=[str(tmp_path / 'D/Media'),
                                 str(tmp_path / 'D/Media/Courses/Old')])
    store = Store(tmp_path / 'index.sqlite', volume='test', mount=tmp_path)
    try:
        crawler.crawl(store, to_roots(s, lambda p: ('test', tmp_path)))
        assert paths(store) == {'D/top.txt', 'D/Media/Courses/week1.txt'}
    finally:
        store.close()


def test_crawl_counts_size_cap_and_indexes_checked_dataset(tmp_path):
    write(tmp_path, ['huge.pdf'])
    os.truncate(tmp_path / 'huge.pdf', 600 * 1024 * 1024)
    write(tmp_path, [f'data/clip_{n:06}.png' for n in range(300)])
    store = Store(tmp_path / 'index.sqlite', volume='test', mount=tmp_path)
    try:
        skipped = Counter()
        crawler.crawl(store, [{'path': str(tmp_path)}], skipped=skipped)
        assert skipped == {'size-cap': 1}
        assert paths(store) == {f'data/clip_{n:06}.png' for n in range(300)}
    finally:
        store.close()


async def test_incremental_reindex_keeps_unchanged_files_and_writes_run_json(tmp_path, monkeypatch):
    class Pool:
        def submit(self, function, *args):
            future = Future()
            try:
                future.set_result(function(*args))
            except Exception as error:
                future.set_exception(error)
            return future

        def shutdown(self, **kwargs):
            pass

    monkeypatch.setattr('omafindd.jobs._pool', Pool)
    root, data = tmp_path / 'docs', tmp_path / 'data'
    write(root, ['note.md'])
    events = []
    kwargs = {'directory': data, 'embedder': FakeEmbedder(),
              'volume_resolver': lambda p: ('test', root), 'progress': events.append}
    await indexing.reindex([{'path': str(root)}], **kwargs)
    store = Store(data / 'index/test.sqlite', volume='test', mount=root)
    before = dict(store.db.execute('SELECT * FROM files').fetchone())
    store.close()
    assert before['state'] == 'done'
    events.clear()
    await indexing.reindex([{'path': str(root)}], force=False, **kwargs)
    store = Store(data / 'index/test.sqlite', volume='test', mount=root)
    try:
        assert dict(store.db.execute('SELECT * FROM files').fetchone()) == before
    finally:
        store.close()
    assert events == []
    run = data / 'index/run.json'
    assert json.loads(run.read_text())['skipped'] == {}
    assert run.stat().st_mode & 0o777 == 0o600


async def test_reindex_skips_offline_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(indexing, 'mounted_volumes', lambda: {}, raising=False)

    def missing(path):
        raise FileNotFoundError(path)

    await indexing.reindex([{'path': str(tmp_path / 'gone'), 'volume': 'offline'}],
                           directory=tmp_path / 'data', embedder=FakeEmbedder(),
                           volume_resolver=missing, volume='offline')
    assert not (tmp_path / 'data/index/offline.sqlite').exists()


async def test_reindex_remaps_root_and_preserves_drive_label(tmp_path, monkeypatch):
    old, new, data = tmp_path / 'old', tmp_path / 'new', tmp_path / 'data'
    write(new, ['docs/note.txt'])
    store = Store(data / 'index/drive.sqlite', volume='drive', mount=old, label='Photos')
    store.close()
    monkeypatch.setattr(indexing, 'mounted_volumes', lambda: {'drive': new}, raising=False)
    selected = []
    monkeypatch.setattr(indexing, 'crawl', lambda store, roots, **kwargs: selected.extend(roots))

    def offline(path):
        raise FileNotFoundError(path)

    await indexing.reindex([{'path': str(old / 'docs'), 'volume': 'drive'}], directory=data,
                           embedder=FakeEmbedder(), volume_resolver=offline,
                           label_resolver=lambda uuid: 'Photos', force=False)
    assert selected[0]['path'] == str(new / 'docs')
    store = Store.open_existing(data / 'index/drive.sqlite', new)
    try:
        assert store.last_mount == new and store.label == 'Photos'
    finally:
        store.close()


@pytest.mark.parametrize('mount,label', [('/home', 'root'), ('/media/Photos', 'Photos')])
async def test_reindex_default_labels_come_from_drive_facts(tmp_path, monkeypatch, mount, label):
    root, data = tmp_path / 'docs', tmp_path / 'data'
    root.mkdir()
    store = Store(data / 'index/v.sqlite', volume='v', mount=root, label='Old label')
    store.close()
    monkeypatch.setattr(indexing, 'mounted_volumes', lambda: {'v': root})
    monkeypatch.setattr(indexing, 'lsblk', lambda: {'blockdevices': [
        {'uuid': 'v', 'label': 'Photos', 'fstype': 'ext4', 'size': 1000,
         'rm': False, 'hotplug': False, 'mountpoints': [mount]}]})
    await indexing.reindex([{'path': str(root), 'volume': 'v'}], directory=data,
                           embedder=FakeEmbedder(), force=False)
    store = Store.open_existing(data / 'index/v.sqlite', root)
    try:
        assert store.label == label
    finally:
        store.close()
