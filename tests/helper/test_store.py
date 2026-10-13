import numpy as np
import pytest


@pytest.mark.parametrize("stage", ["empty", "schema", "uuid"])
def test_open_existing_closes_connection_when_initialization_is_incomplete(
    tmp_path, monkeypatch, stage
):
    import sqlite3

    from omafindd.store import SCHEMA, Store

    path = tmp_path / "v.sqlite"
    with sqlite3.connect(path) as db:
        if stage != "empty":
            db.executescript(SCHEMA)
        if stage == "uuid":
            db.execute("INSERT INTO meta VALUES('volume_uuid','v')")
    db.close()
    connections = []
    connect = sqlite3.connect

    def opened(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", opened)
    with pytest.raises((sqlite3.Error, KeyError)):
        Store.open_existing(path, tmp_path)
    assert len(connections) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")


@pytest.fixture
def store(tmp_path):
    from omafindd.store import Store

    value = Store(tmp_path / "index/v.sqlite", volume="v", mount=tmp_path, label="root")
    yield value
    value.close()


def test_schema_pragmas_permissions_and_meta(store):
    assert [r[1] for r in store.db.execute("PRAGMA table_info(files)")] == [
        "id",
        "path",
        "kind",
        "size",
        "mtime",
        "inode",
        "device",
        "state",
        "detail",
        "info",
        "indexed_at",
    ]
    assert [r[1] for r in store.db.execute("PRAGMA table_info(segments)")] == [
        "id",
        "file",
        "kind",
        "modality",
        "loc",
        "loc_end",
        "excerpt",
        "vec",
    ]
    assert store.db.execute("PRAGMA user_version").fetchone()[0] == 6
    assert store.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert store.db.execute("PRAGMA synchronous").fetchone()[0] == 1
    assert store.db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert {r[0] for r in store.db.execute("SELECT key FROM meta")} == {
        "model_rev",
        "runtime_tag",
        "volume_uuid",
        "volume_label",
    }


def test_model_change_clears_vectors_and_requeues(store, tmp_path):
    from omafindd.crawler import crawl
    from omafindd.extractors import Segment
    from omafindd.store import Store

    (tmp_path / "a.txt").write_text("fixture")
    crawl(store, [{"path": str(tmp_path), "excludes": []}])
    file = store.db.execute("SELECT id FROM files").fetchone()[0]
    store.write(
        file,
        [Segment("chunk", "text", "fixture", loc=1)],
        [np.eye(1, 768)[0]],
        state="done",
        info={},
    )
    other = Store(store.path, volume="v", mount=tmp_path, model_rev="new")
    assert other.db.execute("SELECT state FROM files").fetchone()[0] == "pending"
    assert (
        other.db.execute("SELECT count(*) FROM segments WHERE vec IS NOT NULL").fetchone()[0] == 0
    )
    other.close()


def test_moved_inode_keeps_segments(store, tmp_path):
    from omafindd.crawler import crawl
    from omafindd.extractors import Segment

    path = tmp_path / "a.txt"
    path.write_text("fixture")
    roots = [{"path": str(tmp_path), "excludes": []}]
    crawl(store, roots)
    file = store.db.execute("SELECT id FROM files").fetchone()[0]
    store.write(
        file,
        [Segment("chunk", "text", "fixture", loc=1)],
        [np.eye(1, 768)[0]],
        state="done",
        info={},
    )
    before = list(map(tuple, store.db.execute("SELECT * FROM segments")))
    path.rename(tmp_path / "b.txt")
    crawl(store, roots)
    assert store.db.execute("SELECT path,state FROM files").fetchone()[:] == ("b.txt", "done")
    assert list(map(tuple, store.db.execute("SELECT * FROM segments"))) == before
    assert store.db.execute("SELECT name FROM fts WHERE name != ''").fetchone()[0] == "b.txt"


def test_changed_file_requeues_and_vanished_file_removes_fts(store, tmp_path):
    from omafindd.crawler import crawl

    path = tmp_path / "a.txt"
    path.write_text("fixture")
    roots = [{"path": str(tmp_path), "excludes": []}]
    crawl(store, roots)
    store.db.execute("UPDATE files SET state='done'")
    store.db.commit()
    path.write_text("changed fixture")
    crawl(store, roots)
    assert store.db.execute("SELECT state FROM files").fetchone()[0] == "pending"
    path.unlink()
    crawl(store, roots)
    assert store.db.execute("SELECT count(*) FROM files").fetchone()[0] == 0
    assert store.db.execute("SELECT count(*) FROM fts").fetchone()[0] == 0


def test_secret_files_in_neutral_folder_are_never_opened_or_stored(store, tmp_path, monkeypatch):
    from pathlib import Path

    from omafindd.crawler import crawl
    from omafindd.extractors import extract_text
    from support.corpus import copy_corpus

    folder = copy_corpus(tmp_path / "corpus") / "keys"
    ordinary = folder / "ordinary.txt"
    ordinary.write_text("fixture")
    names = {"id_rsa", "id_rsa.txt", "private.pem", "credentials.json", "secrets.yml",
             "secret.md", "a.kdbx", "b.age", ".env.local"}
    opened = []
    original = Path.open

    def reject(path, *args, **kwargs):
        assert path.name not in names, "opened secret"
        opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject)
    crawl(store, [{"path": str(folder), "excludes": []}])
    paths = [store.mount / row[0] for row in store.db.execute("SELECT path FROM files")]
    assert paths == [ordinary]
    assert extract_text(paths[0]).segments[0].text == "fixture"
    assert opened == [ordinary]


def test_volume_uses_findmnt_target(tmp_path):
    import subprocess

    from omafindd.store import volume_for

    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "uuid /home\n", "")

    assert volume_for(tmp_path, run=run) == ("uuid", __import__("pathlib").Path("/home"))


def test_forced_crawl_keeps_content_until_commit(store, tmp_path):
    from omafindd.crawler import crawl
    from omafindd.extractors import Segment

    (tmp_path / "a.txt").write_text("fixture")
    roots = [{"path": str(tmp_path)}]
    crawl(store, roots)
    file = store.db.execute("SELECT id FROM files").fetchone()[0]
    store.write(
        file, [Segment("chunk", "text", "fixture")], [np.eye(1, 768)[0]], state="done", info={}
    )
    before = list(map(tuple, store.db.execute("SELECT * FROM segments")))
    assert crawl(store, roots, force=True) == [file]
    assert store.db.execute("SELECT state FROM files").fetchone()[0] == "pending"
    assert list(map(tuple, store.db.execute("SELECT * FROM segments"))) == before


@pytest.mark.parametrize("listing", ["uuid /\nuuid /home\n", "uuid /home\nuuid /\n"])
def test_duplicate_uuid_uses_home_mount_for_all_roots(monkeypatch, listing):
    import subprocess
    from pathlib import Path

    from omafindd.store import mounted_volumes, volume_for

    monkeypatch.setattr(Path, "home", lambda: Path("/home/u"))

    def run(argv, **kwargs):
        if "-T" not in argv:
            output = listing
        else:
            output = "uuid /home\n" if argv[-1].startswith("/home") else "uuid /\n"
        return subprocess.CompletedProcess(argv, 0, output, "")

    assert mounted_volumes(run=run)["uuid"] == Path("/home")
    assert volume_for(Path("/home/u/docs"), run=run) == ("uuid", Path("/home"))
    assert volume_for(Path("/opt/docs"), run=run) == ("uuid", Path("/home"))


def test_other_duplicate_uuid_uses_shortest_mount(monkeypatch):
    import subprocess
    from pathlib import Path

    from omafindd.store import mounted_volumes

    monkeypatch.setattr(Path, "home", lambda: Path("/home/u"))

    def run(argv, **kwargs):
        output = "home /home\n" if "-T" in argv else "usb /mnt\nusb /media/usb\n"
        return subprocess.CompletedProcess(argv, 0, output, "")

    assert mounted_volumes(run=run)["usb"] == Path("/mnt")


def test_vector_change_probe_uses_index_without_reading_vector_blobs(store):
    plan = store.db.execute(
        "EXPLAIN QUERY PLAN SELECT count(*),coalesce(max(id),0) "
        "FROM segments WHERE vec IS NOT NULL"
    )
    assert any("USING INDEX" in row[3] for row in plan)


def test_crawl_ancestor_of_home_mount_preserves_existing_file_ids(store, tmp_path):
    from omafindd.crawler import crawl

    home = tmp_path / "home"
    home.mkdir()
    (home / "inside.txt").write_text("fixture")
    (tmp_path / "outside.txt").write_text("fixture")
    store.mount = home
    crawl(store, [{"path": str(home)}])
    file = store.db.execute("SELECT id FROM files").fetchone()[0]
    with store.db:
        store.db.execute("UPDATE files SET state='done' WHERE id=?", (file,))
    crawl(store, [{"path": str(tmp_path)}])
    assert store.db.execute("SELECT id,state FROM files WHERE path='inside.txt'").fetchone()[:] == (
        file, "done"
    )
    pending = store.db.execute("SELECT path FROM files WHERE state='pending'").fetchone()[0]
    assert pending == "../outside.txt"


def test_volume_for_reuses_supplied_mounts_without_rediscovering(tmp_path):
    import subprocess

    from omafindd.store import volume_for

    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "uuid /\n", "")

    assert volume_for(tmp_path, run=run, mounts={"uuid": tmp_path}) == ("uuid", tmp_path)
    assert calls == [["findmnt", "-no", "UUID,TARGET", "-T", str(tmp_path)]]


def test_mounts_without_uuid_use_mountinfo_device_without_stat(monkeypatch):
    import subprocess
    from pathlib import Path

    from omafindd.store import mounted_volumes

    read = Path.read_text
    original_stat = Path.stat

    def mountinfo(path, *args, **kwargs):
        if path == Path("/proc/self/mountinfo"):
            return "41 1 8:17 / /media/usb rw - ext4 /dev/sdb1 rw\n"
        return read(path, *args, **kwargs)

    def stat(path, *args, **kwargs):
        if path == Path("/media/usb"):
            pytest.fail(f"mount discovery statted {path}")
        return original_stat(path, *args, **kwargs)

    def run(argv, **kwargs):
        output = " /media/usb\n" if "-T" not in argv else ""
        return subprocess.CompletedProcess(argv, 0, output, "")

    monkeypatch.setattr(Path, "read_text", mountinfo)
    monkeypatch.setattr(Path, "stat", stat)
    assert mounted_volumes(run=run) == {"dev-2065": Path("/media/usb")}
