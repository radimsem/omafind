import io
import os
from pathlib import Path

import pytest
from omafindd import discovery


class Process:
    def __init__(self, names):
        self.stdout = io.BytesIO(b'\0'.join(os.fsencode(name) for name in names) + b'\0')
        self.stderr = io.BytesIO()
        self.terminated = False
        self.reaped = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.reaped = True

    def terminate(self):
        self.terminated = True

    def wait(self):
        return 0


def test_non_system_volumes_from_lsblk():
    data = {'blockdevices': [
        {'uuid': 'boot', 'mountpoints': ['/boot']},
        {'uuid': 'root', 'fstype': 'btrfs',
         'mountpoints': ['/', '/home', '/var/log', '/var/cache/pacman/pkg']},
        {'uuid': 'swap', 'mountpoints': ['[SWAP]']},
        {'uuid': 'container', 'mountpoints': [None]},
    ]}
    assert discovery.non_system_volumes(data) == []
    data['blockdevices'].append({'uuid': 'usb', 'fstype': 'exfat', 'hotplug': True,
                                 'mountpoints': ['/media/usb']})
    assert discovery.non_system_volumes(data) == [('usb', Path('/media/usb'))]


def test_list_dirs_hides_dot_and_heavy_and_reports_missing(tmp_path):
    for name in ('Zebra', 'apple', '.hidden', 'node_modules'):
        (tmp_path / name).mkdir()
    (tmp_path / 'file').touch()
    assert discovery.list_dirs('~', home=tmp_path) == {
        'path': '~', 'abs': str(tmp_path), 'dirs': ['apple', 'Zebra'], 'error': None}
    assert discovery.list_dirs('~/missing', home=tmp_path)['error'] == 'missing'
    assert discovery.list_dirs('~/file', home=tmp_path)['error'] == 'not-a-directory'


def test_list_dirs_reports_an_unreadable_directory(tmp_path, monkeypatch):
    def denied(path):
        raise PermissionError(13, 'Permission denied', str(path))

    monkeypatch.setattr(discovery.os, 'scandir', denied)
    assert discovery.list_dirs('/root', home=tmp_path) == {
        'path': '/root', 'abs': '/root', 'dirs': [], 'error': 'denied'}


def test_xdg_dirs_reads_home_and_omits_home_itself(tmp_path):
    config = tmp_path / '.config/user-dirs.dirs'
    config.parent.mkdir()
    config.write_text('XDG_DOCUMENTS_DIR="$HOME/Documents"\nXDG_MUSIC_DIR="${HOME}/Music"\n'
                      'XDG_DESKTOP_DIR="$HOME"\nXDG_TEMPLATES_DIR="$HOME"\n')
    assert discovery.xdg_dirs(tmp_path) == {
        'DOCUMENTS': tmp_path / 'Documents', 'MUSIC': tmp_path / 'Music'}


def test_volume_lookup_reuses_mount_table_and_prefers_inner_mount(monkeypatch):
    from omafindd import store

    calls = []

    def mounted_volumes():
        calls.append(True)
        return {'home-volume': Path('/home'), 'external-volume': Path('/home/u/drive')}

    monkeypatch.setattr(store, 'mounted_volumes', mounted_volumes)
    monkeypatch.setattr(discovery, '_volume_of', lambda p: pytest.fail('per-candidate probe'))
    lookup = discovery._volume_lookup({'blockdevices': [
        {'uuid': 'boot-volume', 'mountpoints': ['/boot']}]})
    assert lookup(Path('/home/u/Documents')) == ('home-volume', Path('/home'))
    assert lookup(Path('/home/u/drive/Documents')) == ('external-volume', Path('/home/u/drive'))
    assert lookup(Path('/boot/docs')) == ('boot-volume', Path('/boot'))
    assert calls == [True]


ZERO = dict.fromkeys((*discovery.KINDS, "dirs"), 0)


def test_folders_hide_symlinks_hidden_heavy_and_secrets(tmp_path):
    for name in ("Documents", "code", ".cache", "node_modules", "secrets"):
        (tmp_path / name).mkdir()
    (tmp_path / "code/.git").mkdir()
    (tmp_path / "Documents/tax").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "Documents")
    (tmp_path / "file.txt").write_text("x")
    rows = discovery.folders(tmp_path)
    assert rows == [
        {"path": str(tmp_path / "code"), "name": "code", "repo": True, "worktree": False,
         "hasChildren": False},
        {"path": str(tmp_path / "Documents"), "name": "Documents", "repo": False, "worktree": False,
         "hasChildren": True},
    ]


def test_top_reads_one_level_and_marks_xdg_and_volumes(tmp_path):
    home = tmp_path / "home"
    for name in ("Documents", "Pictures", "code"):
        (home / name).mkdir(parents=True)
    drive = tmp_path / "drive"
    drive.mkdir()
    lsblk = {"blockdevices": [{"uuid": "usb", "mountpoints": [str(drive)], "rm": True}]}
    body = discovery.top(home=home, lsblk=lsblk,
                         xdg={"DOCUMENTS": home / "Documents", "TEMPLATES": home / "code"},
                         volume_of=lambda path: ("root", Path("/")))
    rows = {row["name"]: row for row in body["folders"]}
    assert list(rows) == ["code", "Documents", "Pictures", str(drive)]
    assert [name for name, row in rows.items() if row["xdg"]] == ["Documents"]
    assert rows[str(drive)]["volume"] == "usb" and rows["Documents"]["volume"] == "root"
    assert body["roots"] == [{"path": str(home), "volume": "root"},
                             {"path": str(drive), "volume": "usb"}]


def test_top_for_a_volume_lists_the_mount(tmp_path):
    drive = tmp_path / "drive"
    (drive / "Photos").mkdir(parents=True)
    lsblk = {"blockdevices": [{"uuid": "usb", "mountpoints": [str(drive)], "rm": True}]}
    body = discovery.top(home=tmp_path / "home", volume="usb", lsblk=lsblk)
    assert body["roots"] == [{"path": str(drive), "volume": "usb"}]
    assert [(r["name"], r["volume"], r["xdg"]) for r in body["folders"]] == [
        ("Photos", "usb", False)]
    with pytest.raises(ValueError):
        discovery.top(home=tmp_path / "home", volume="gone", lsblk=lsblk)


def test_top_caps_rows_at_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "LIMIT", 3)
    for n in range(5):
        (tmp_path / f"d{n}").mkdir()
    body = discovery.top(home=tmp_path, lsblk={"blockdevices": []}, xdg={},
                         volume_of=lambda path: ("root", Path("/")))
    assert [row["name"] for row in body["folders"]] == ["d0", "d1", "d2"]


def test_walk_rolls_counts_up_in_batches(tmp_path):
    (tmp_path / "a/b").mkdir(parents=True)
    (tmp_path / "a/b/x.md").write_text("x")
    (tmp_path / "a/y.pdf").write_bytes(b"%PDF")
    (tmp_path / "a/b/z.png").write_bytes(b"png")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden/w.md").write_text("w")
    (tmp_path / "a/notes.bin").write_bytes(b"0")
    ticks = iter(range(1000))
    walk = discovery.Walk(tmp_path, clock=lambda: next(ticks))
    batches = []
    walk.run(batches.append, every=1)
    assert [batch["done"] for batch in batches] == [False] * (len(batches) - 1) + [True]
    assert len(batches) >= 2
    final = batches[-1]
    assert final["root"] == str(tmp_path) and final["datasets"] == []
    assert final["repos"] == [] and final["worktrees"] == []
    assert isinstance(final["seconds"], float)
    both = ZERO | {"text": 1, "pdf": 1, "image": 1}
    assert walk.count(str(tmp_path)) == both | {"dirs": 3}
    assert walk.count(str(tmp_path / "a")) == both | {"dirs": 2}
    assert walk.count(str(tmp_path / "a/b")) == ZERO | {"text": 1, "image": 1, "dirs": 1}
    assert walk.count(str(tmp_path / ".hidden")) == ZERO
    merged = {}
    for batch in batches:
        merged.update(batch["counts"])
    assert merged[str(tmp_path / "a")] == both | {"dirs": 2}


def test_walk_reports_media_datasets(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    for n in range(300):
        (folder / f"clip_{n:06}.png").write_bytes(b"png")
    walk = discovery.Walk(tmp_path)
    batches = []
    walk.run(batches.append)
    evidence = {"kind": "image", "files": 300, "named": 100}
    assert batches[-1]["datasets"] == [{"path": str(folder), **evidence}]
    assert walk.dataset(str(folder)) == evidence


def test_walk_of_a_missing_root_ends_with_error(tmp_path):
    walk = discovery.Walk(tmp_path / "gone")
    batches = []
    walk.run(batches.append)
    assert batches[-1]["done"] is True and batches[-1]["error"]
    assert walk.snapshot()["error"] == batches[-1]["error"]


def test_children_counts_are_null_until_the_walk_reaches_them(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "b/x.md").write_text("x")
    walk = discovery.Walk(tmp_path)
    assert [d["counts"] for d in discovery.children(tmp_path, walk)["dirs"]] == [None, None]
    walk.run(lambda batch: None)
    body = discovery.children(tmp_path, walk)
    assert body["error"] is None
    assert [(d["name"], sum(d["counts"][kind] for kind in discovery.KINDS))
            for d in body["dirs"]] == [("b", 1), ("a", 0)]


def test_children_mark_datasets_with_evidence(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    for n in range(300):
        (folder / f"frame_{n:06}.jpg").write_bytes(b"jpg")
    walk = discovery.Walk(tmp_path)
    walk.run(lambda batch: None)
    row = discovery.children(tmp_path, walk)["dirs"][0]
    assert row["rule"] == "dataset"
    assert row["evidence"] == {"kind": "image", "files": 300, "named": 100}


def test_children_of_unreadable_folder_report_error(tmp_path):
    body = discovery.children(tmp_path / "missing")
    assert body == {"path": str(tmp_path / "missing"), "dirs": [],
                    "error": "No such file or directory"}


def test_stop_terminates_and_reaps_the_fd_process(tmp_path):
    process = Process([tmp_path / 'a.md', tmp_path / 'b.md'])
    walk = discovery.Walk(tmp_path, popen=lambda *args, **kwargs: process)
    batches = []

    def emit(batch):
        batches.append(batch)
        if not batch['done']:
            walk.stop()

    walk.run(emit, every=0)
    assert process.terminated and process.reaped
    assert batches[-1]['done']
    assert walk.count(str(tmp_path))['text'] == 1


def test_top_only_peeks_at_folders_within_the_row_limit(tmp_path, monkeypatch):
    for name in ('a', 'b', 'c', 'd'):
        (tmp_path / name).mkdir()
    reads = []
    scandir = discovery.os.scandir

    def read(path):
        reads.append(Path(path))
        return scandir(path)

    monkeypatch.setattr(discovery, 'LIMIT', 2)
    monkeypatch.setattr(discovery.os, 'scandir', read)
    rows = discovery.folders(tmp_path)
    assert [row['name'] for row in rows] == ['a', 'b']
    assert reads == [tmp_path, tmp_path / 'a', tmp_path / 'b']


def test_walk_rolls_up_directory_counts_without_counting_them_as_files(tmp_path):
    process = Process([tmp_path / 'a/b/note.md', tmp_path / 'a/c/note.md'])
    walk = discovery.Walk(tmp_path, popen=lambda *args, **kwargs: process)
    walk.run(lambda batch: None)
    assert walk.count(str(tmp_path))['dirs'] == 4
    assert walk.count(str(tmp_path / 'a'))['dirs'] == 3
    assert walk.count(str(tmp_path / 'a/b'))['dirs'] == 1
    assert walk.count(str(tmp_path))['text'] == 2


@pytest.mark.skipif(os.geteuid() == 0, reason="root can traverse chmod 000 folders")
def test_folders_tolerate_an_untraversable_child(tmp_path):
    child = tmp_path / "denied"
    child.mkdir()
    child.chmod(0)
    try:
        assert discovery.folders(tmp_path) == [
            {"path": str(child), "name": "denied", "repo": False, "worktree": False,
             "hasChildren": False}]
    finally:
        child.chmod(0o700)


def test_top_keeps_volumes_when_home_exceeds_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "LIMIT", 3)
    home, drive = tmp_path / "home", tmp_path / "drive"
    drive.mkdir()
    for n in range(5):
        (home / f"d{n}").mkdir(parents=True)
    body = discovery.top(home=home, xdg={},
                         lsblk={"blockdevices": [{"uuid": "usb", "mountpoints": [str(drive)]}]},
                         volume_of=lambda path: ("root", Path("/")))
    assert [row["name"] for row in body["folders"]] == ["d0", "d1", "d2", str(drive)]


def test_discovery_skips_non_utf8_names(tmp_path):
    import json

    bad_dir = os.fsencode(tmp_path) + b"/bad\xff"
    os.mkdir(bad_dir)
    bad_file = os.fsencode(tmp_path) + b"/bad\xff.md"
    with open(bad_file, "wb") as stream:
        stream.write(b"fixture")
    (tmp_path / "ok").mkdir()
    (tmp_path / "ok/note.md").write_text("fixture")
    rows = discovery.folders(tmp_path)
    assert [row["name"] for row in rows] == ["ok"]
    walk = discovery.Walk(tmp_path)
    batches = []
    walk.run(batches.append)
    assert batches[-1]["done"] and not batches[-1].get("error")
    assert walk.count(str(tmp_path))["text"] == 1
    for body in [rows, *batches]:
        json.dumps(body, ensure_ascii=False).encode()


def test_walk_uses_media_tallies_instead_of_retaining_paths(tmp_path, monkeypatch):
    from omafindd import rules

    folder = tmp_path / "data"
    process = Process(folder / f"clip_{n:06}.png" for n in range(300))
    seen = []
    original = rules.dataset_counts

    def evidence(groups):
        seen.append(dict(groups))
        return original(groups)

    monkeypatch.setattr(rules, "dataset_counts", evidence)
    walk = discovery.Walk(tmp_path, popen=lambda *args, **kwargs: process)
    walk.run(lambda batch: None)
    assert seen == [{(str(folder), "image"): [300, 300]}]
    assert walk.dataset(str(folder)) == {"kind": "image", "files": 300, "named": 100}


def _repo(path):
    (path / ".git").mkdir(parents=True)


def _linked(path, gitdir, *, worktree):
    path.mkdir(parents=True)
    gitdir.mkdir(parents=True)
    if worktree:
        (gitdir / "commondir").write_text("../..\n")
    (path / ".git").write_text(f"gitdir: {gitdir}\n")


def test_git_kind_tells_repo_worktree_submodule_and_plain(tmp_path):
    _repo(tmp_path / "main")
    _linked(tmp_path / "wt", tmp_path / "main/.git/worktrees/wt", worktree=True)
    _linked(tmp_path / "main/sub", tmp_path / "main/.git/modules/sub", worktree=False)
    (tmp_path / "plain").mkdir()
    (tmp_path / "odd").mkdir()
    (tmp_path / "odd/.git").write_text("not a gitdir line")
    assert [discovery.git_kind(str(tmp_path / name)) for name in
            ("main", "wt", "main/sub", "plain", "odd")] == [
        "repo", "worktree", "repo", None, None]


def test_relative_gitdir_resolves_against_the_folder(tmp_path):
    _repo(tmp_path / "main")
    (tmp_path / "main/.git/worktrees/wt").mkdir(parents=True)
    (tmp_path / "main/.git/worktrees/wt/commondir").write_text("../..\n")
    (tmp_path / "wt").mkdir()
    (tmp_path / "wt/.git").write_text("gitdir: ../main/.git/worktrees/wt\n")
    assert discovery.git_kind(str(tmp_path / "wt")) == "worktree"


def test_rows_and_walk_report_repos_and_worktrees(tmp_path):
    _repo(tmp_path / "proj/main")
    (tmp_path / "proj/main/a.md").write_text("a")
    _linked(tmp_path / "proj/wt", tmp_path / "proj/main/.git/worktrees/wt", worktree=True)
    (tmp_path / "proj/wt/b.md").write_text("b")
    (tmp_path / "proj/code-only").mkdir()
    (tmp_path / "proj/code-only/.git").mkdir()
    (tmp_path / "proj/code-only/x.py").write_text("x")
    rows = {row["name"]: row for row in discovery.folders(tmp_path / "proj")}
    assert (rows["main"]["repo"], rows["main"]["worktree"]) == (True, False)
    assert (rows["wt"]["repo"], rows["wt"]["worktree"]) == (False, True)
    walk = discovery.Walk(tmp_path)
    batches = []
    walk.run(batches.append)
    assert batches[-1]["repos"] == [str(tmp_path / "proj/code-only"), str(tmp_path / "proj/main")]
    assert batches[-1]["worktrees"] == [str(tmp_path / "proj/wt")]
    assert walk.snapshot()["worktrees"] == [str(tmp_path / "proj/wt")]
