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


@pytest.mark.parametrize("at_root,rule", [(False, "dataset"), (True, None)])
def test_dataset_threshold_and_root_exemption(tmp_path, at_root, rule):
    from omafindd.rules import Skip, keep

    folder = tmp_path if at_root else tmp_path / "data"
    folder.mkdir(exist_ok=True)
    paths = []
    for n in range(300):
        path = folder / f"clip_{n:06}.txt"
        path.write_text("fixture")
        paths.append(path)
    kept = list(keep(paths, root=tmp_path))
    assert len(kept) == 300
    assert all(
        (isinstance(p, Skip) and p.rule == rule) if rule else isinstance(p, Path) for p in kept
    )


def test_camera_names_are_not_datasets(tmp_path):
    from omafindd.rules import looks_machine_named

    assert looks_machine_named("frame-0042")
    assert looks_machine_named("3f9a1c0e-abcd")
    assert not looks_machine_named("IMG_000123")
    assert not looks_machine_named("invoice")


def test_size_cap_is_post_filter(tmp_path):
    from omafindd.rules import Skip, keep

    path = tmp_path / "large.txt"
    with path.open("wb") as stream:
        stream.truncate(16 * 1024 * 1024 + 1)
    assert list(keep([path], root=tmp_path)) == [Skip(path, "size-cap")]


def test_explain_counts_names_without_opening_files(tmp_path):
    from omafindd.rules import explain, walk

    (tmp_path / "visible.txt").write_text("fixture")
    (tmp_path / ".hidden.txt").write_text("fixture")
    (tmp_path / "secret.txt").write_text("fixture")
    (tmp_path / "build").mkdir()
    (tmp_path / "build/a.txt").write_text("fixture")
    counts = explain(tmp_path)
    assert counts == {"dot": 1, "heavy": 1, "secrets": 1}
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
    assert list(keep([path], root=tmp_path)) == [path]
    with path.open("ab") as stream:
        stream.write(b"x")
    assert list(keep([path], root=tmp_path)) == [Skip(path, "size-cap")]
