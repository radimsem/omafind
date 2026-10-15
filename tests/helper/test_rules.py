import os
import subprocess
from pathlib import Path

import pytest
from support.corpus import copy_corpus


def test_secret_globs_cover_every_digup_secret():
    from omafindd.rules import SECRET_GLOBS, fd_args, reason

    for name in [
        "id_rsa",
        ".env.local",
        "secrets.yml",
        "credentials.json",
        "a.kdbx",
        "b.age",
        "ID_ED25519.txt",
        "Certificate.PEM",
        "a.asc",
    ]:
        assert reason(Path(name)) == "secrets"
    args = fd_args(Path("/root"), excludes=[], kinds=["text", "pdf"])
    assert all(glob in args for glob in SECRET_GLOBS)
    assert "--no-global-ignore-file" in args
    assert not {"-H", "-I"}.intersection(args)


def test_fd_keeps_neither_secrets_nor_ignore_folder(tmp_path):
    from omafindd.rules import walk

    root = copy_corpus(tmp_path / "corpus")
    found = list(walk(root, excludes=[]))
    assert found
    names = {"id_rsa", "id_rsa.txt", "private.pem", "credentials.json", "secrets.yml",
             "secret.md", "a.kdbx", "b.age", ".env.local"}
    assert (root / "keys").is_dir()
    assert not any(p.name in names or "ignored" in p.parts for p in found)


def test_fd_secret_globs_remove_each_file_in_neutral_folder(tmp_path):
    from omafindd.rules import fd_args

    root = copy_corpus(tmp_path / "corpus")
    keys = root / "keys"
    assert keys.is_dir()
    (keys / "ordinary.txt").write_text("fixture")
    args = fd_args(keys, excludes=[], kinds=[])
    result = subprocess.run([args[0], "-H", *args[1:]], capture_output=True, check=True)
    assert set(result.stdout.split(b"\0")) - {b""} == {str(keys / "ordinary.txt").encode()}


def test_parent_gitignore_is_honored_when_listing_root(tmp_path):
    from omafindd.rules import walk

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("excluded/\n")
    (tmp_path / "excluded").mkdir()
    (tmp_path / "excluded/a.md").write_text("fixture")
    (tmp_path / "kept.md").write_text("fixture")
    assert list(walk(tmp_path, excludes=[])) == [tmp_path / "kept.md"]


def test_root_excludes_apply_as_paths(tmp_path):
    from omafindd.rules import walk

    (tmp_path / "out").mkdir()
    (tmp_path / "out/a.txt").write_text("fixture")
    (tmp_path / "yes.txt").write_text("fixture")
    assert list(walk(tmp_path, excludes=[str(tmp_path / "out")])) == [tmp_path / "yes.txt"]


def test_keep_never_drops_a_checked_dataset(tmp_path):
    from omafindd.rules import keep

    folder = tmp_path / "data"
    folder.mkdir()
    paths = []
    for n in range(300):
        path = folder / f"clip_{n:06}.png"
        path.write_bytes(b"png")
        paths.append(path)
    assert list(keep(paths)) == paths


@pytest.mark.parametrize("count,suffix,expected", [
    (300, "png", {"kind": "image", "files": 300, "named": 100}),
    (299, "png", None),
    (300, "txt", None),
    (300, "pdf", None),
    (300, "mp4", {"kind": "video", "files": 300, "named": 100}),
    (300, "flac", {"kind": "audio", "files": 300, "named": 100}),
])
def test_dataset_is_media_only_with_evidence(count, suffix, expected):
    from omafindd.rules import datasets

    paths = [Path(f"/h/data/clip_{n:06}.{suffix}") for n in range(count)]
    found = datasets(paths, root=Path("/h"))
    assert found == ({Path("/h/data"): expected} if expected else {})


def test_dataset_root_is_exempt():
    from omafindd.rules import datasets

    assert datasets([Path(f"/h/clip_{n:06}.png") for n in range(300)], root=Path("/h")) == {}


@pytest.mark.parametrize("stem,machine", [
    ("frame-0042", True), ("3f9a1c0e-abcd", True),
    ("IMG_000123", False), ("DSCN0042", False), ("PXL_20240518_101010", False),
    ("MVIMG_0001", False), ("VID_0042", False), ("GOPR0042", False),
    ("2024-05-18", False), ("2024-05-18_10-10-10", False), ("2024-05-18 101010", False),
    ("20240518", False), ("20240518_101010", False), ("20240518101010", False),
    ("19991231-235959", False), ("20241318", True), ("20240532", True),
    ("invoice", False),
])
def test_camera_and_date_names_are_not_machine_names(stem, machine):
    from omafindd.rules import looks_machine_named

    assert looks_machine_named(stem) is machine


def test_size_cap_is_post_filter(tmp_path):
    from omafindd.rules import Skip, keep

    path = tmp_path / "large.txt"
    with path.open("wb") as stream:
        stream.truncate(16 * 1024 * 1024 + 1)
    assert list(keep([path])) == [Skip(path, "size-cap")]


def test_walk_leaves_out_hidden_heavy_and_secret_names(tmp_path):
    from omafindd.rules import walk

    (tmp_path / "visible.txt").write_text("fixture")
    (tmp_path / ".hidden.txt").write_text("fixture")
    (tmp_path / "secret.txt").write_text("fixture")
    (tmp_path / "build").mkdir()
    (tmp_path / "build/a.txt").write_text("fixture")
    assert list(walk(tmp_path, excludes=[])) == [tmp_path / "visible.txt"]


@pytest.mark.parametrize("folder", ["secrets", ".ssh", "build"])
def test_selected_root_still_obeys_global_rules(tmp_path, folder):
    from omafindd.rules import walk

    root = tmp_path / folder
    root.mkdir()
    (root / "ordinary.txt").write_text("fixture")
    assert list(walk(root, excludes=[])) == []


@pytest.mark.parametrize("name,kind,cap", [("a.mp4", "video", 8192), ("a.flac", "audio", 2048)])
def test_media_size_caps(tmp_path, name, kind, cap):
    from omafindd.rules import Skip, classify, keep

    path = tmp_path / name
    with path.open("wb") as stream:
        stream.truncate(cap * 1024 * 1024)
    assert classify(path) == kind
    assert list(keep([path])) == [path]
    with path.open("ab") as stream:
        stream.write(b"x")
    assert list(keep([path])) == [Skip(path, "size-cap")]


def test_datasets_never_stat(monkeypatch):
    from omafindd.rules import datasets

    def stat(*args, **kwargs):
        raise AssertionError('dataset detection must read names only')

    paths = [Path(f'/h/data/clip_{n:06}.png') for n in range(300)]
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'stat', stat)
        patch.setattr(os, 'stat', stat)
        found = datasets(paths, root=Path('/h'))
    assert found == {Path('/h/data'): {'kind': 'image', 'files': 300, 'named': 100}}


def test_reason_matches_secret_globs_for_names_and_ancestors():
    import fnmatch

    from omafindd import rules

    names = ['.ENV.local.md', 'Secret-notes.txt', 'id_ED25519.pub', 'x.PEM',
             'normal.md', 'notsecret.md', '.hidden', 'build', 'a\n.env.md',
             'credentials', 'x.kdbx', 'x.pem.bak']
    for name in names:
        for path in (Path(name), Path(name) / 'nested/note.md'):
            expected = ('secrets' if any(fnmatch.fnmatchcase(part, glob)
                                        for part in path.parts for glob in rules.SECRET_GLOBS)
                        else 'heavy' if any(p in rules.HEAVY_GLOBS for p in path.parts)
                        else 'dot' if any(p.startswith('.') for p in path.parts) else None)
            assert rules.reason(path) == expected


@pytest.mark.parametrize('name', ['.md', '..md', '...pdf', 'note.MD', 'note.',
                                  '.note.md', 'no-extension', 'a..png'])
def test_classify_name_matches_path_suffix(name):
    from omafindd import rules

    assert rules.classify_name(name) == rules.classify(Path(name))


def test_reason_handles_deep_paths_without_recursion():
    from omafindd import rules

    parent = Path(*(['a'] * 1200))
    assert rules.reason(parent / 'note.md') is None
    assert rules.reason(parent / '.env.md') == 'secrets'



def test_walk_drains_large_stderr_without_a_pipe(tmp_path):
    import io

    from omafindd.rules import walk

    class Process:
        stdout = io.BytesIO(b"")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def wait(self):
            return 1

    def run(args, *, stdout, stderr, cwd):
        # A pipe would block a child before it can close stdout.
        assert stderr != subprocess.PIPE
        stderr.write(b"permission warning\n" * 10000 + b"last warning.\n")
        return Process()

    with pytest.raises(OSError, match=r"^fd failed: last warning\.$"):
        list(walk(tmp_path, excludes=[], run=run))
