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


def test_datasets_never_stat(monkeypatch):
    from omafindd.rules import datasets

    def stat(*args, **kwargs):
        raise AssertionError('dataset detection must read names only')

    monkeypatch.setattr(Path, 'stat', stat)
    monkeypatch.setattr(os, 'stat', stat)
    paths = [Path(f'/h/data/clip_{n:06}.png') for n in range(300)]
    assert datasets(paths, root=Path('/h')) == {Path('/h/data')}


def test_explain_unchanged_after_refactor(tmp_path):
    from omafindd.rules import explain, removed, rule_dirs

    for name in ('a.txt', '.hidden/a.txt', '.hidden/deeper/b.txt', 'build/a.txt', 'secret.md'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    assert explain(tmp_path) == {'dot': 2, 'heavy': 1, 'secrets': 1}
    assert rule_dirs(removed(tmp_path, 'dot'), 'dot', root=tmp_path) == 1
    assert rule_dirs(removed(tmp_path, 'heavy'), 'heavy', root=tmp_path) == 1


@pytest.mark.parametrize('name,family', [('.env.md', '.env'), ('.ENV.local.md', '.env'),
                                      ('ID_RSA.txt', 'id_rsa'), ('passwords.kdbx', '.kdbx'),
                                      ('Certificate.PEM', '.pem'), ('secrets.md', 'secret')])
def test_secret_family_names(name, family):
    from omafindd.rules import secret_family

    assert secret_family(name) == family


def test_explain_keeps_existing_hidden_secret_counts(tmp_path):
    from omafindd.rules import explain

    (tmp_path / '.env.txt').touch()
    assert explain(tmp_path) == {'dot': 0, 'heavy': 0, 'secrets': 0}


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


def test_rule_directory_counts_do_not_need_a_baseline(tmp_path):
    from omafindd import rules

    for name in ('visible.md', '.hidden/note.md', 'build/note.md'):
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.touch()
    for rule in ('dot', 'heavy'):
        actual = rules.rule_dirs(rules.removed(tmp_path, rule), rule, root=tmp_path)
        relaxed = rules.removed(tmp_path, rule, as_paths=False, baseline=())
        assert rules.rule_dirs(relaxed, rule, root=tmp_path) == actual == 1


def test_reason_handles_deep_paths_without_recursion():
    from omafindd import rules

    parent = Path(*(['a'] * 1200))
    assert rules.reason(parent / 'note.md') is None
    assert rules.reason(parent / '.env.md') == 'secrets'
