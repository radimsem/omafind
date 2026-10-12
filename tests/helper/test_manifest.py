import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def validate(root):
    manifest = json.loads((root / "manifest.json").read_text())
    assert type(manifest.get("schemaVersion")) in (int, float)
    assert manifest["schemaVersion"] == 1
    assert all(key in manifest for key in ("id", "name", "version", "kinds", "entryPoints"))
    plugin_id = manifest["id"]
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", plugin_id)
    assert ".." not in plugin_id and not plugin_id.startswith("omarchy.")
    assert isinstance(manifest["kinds"], list) and manifest["kinds"]
    assert isinstance(manifest["entryPoints"], dict)
    for entry in manifest["entryPoints"].values():
        assert isinstance(entry, str) and entry and ".." not in entry and "\n" not in entry
        assert not Path(entry).is_absolute()
        assert (root / entry).is_file()
    for kind, entry in {
        "service": "service", "bar-widget": "barWidget", "panel": "panel", "overlay": "overlay",
    }.items():
        if kind in manifest["kinds"]:
            assert entry in manifest["entryPoints"]
    for directory, dirs, files in os.walk(root):
        # The local venv is not part of a plugin installation.
        dirs[:] = [name for name in dirs if name != ".git"
                   and Path(directory) / name != root / "helper/.venv"]
        assert not any((Path(directory) / name).is_symlink()
                       for name in dirs + files if name != ".git")
    return manifest


def test_real_manifest_passes_validator():
    assert validate(ROOT)["id"] == "radimsem.omafind"


@pytest.mark.parametrize("mutation", [
    "schema-string", "schema-bool", "schema-version", "reserved-id", "invalid-id",
    "double-dot-id", "missing-id", "missing-name", "missing-version", "missing-kinds",
    "missing-entrypoints", "empty-kinds", "string-kinds", "list-entrypoints",
    "absolute", "parent", "newline", "empty-path", "non-string-path", "missing-file",
    "missing-service", "missing-overlay", "missing-panel", "missing-bar-widget",
    "symlink-file", "symlink-directory",
])
def test_invalid_manifest_is_rejected(tmp_path, mutation):
    root = tmp_path / "plugin"
    shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(
        ".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules",
    ))
    manifest = json.loads((root / "manifest.json").read_text())
    if mutation.startswith("schema-"):
        manifest["schemaVersion"] = {
            "schema-string": "1", "schema-bool": True, "schema-version": 2,
        }[mutation]
    elif mutation.endswith("-id") and mutation != "missing-id":
        manifest["id"] = {
            "reserved-id": "omarchy.omafind", "invalid-id": "/omafind",
            "double-dot-id": "radimsem..omafind",
        }[mutation]
    elif mutation in ("missing-id", "missing-name", "missing-version", "missing-kinds",
                      "missing-entrypoints"):
        del manifest["entryPoints" if mutation == "missing-entrypoints" else mutation[8:]]
    elif mutation == "empty-kinds":
        manifest["kinds"] = []
    elif mutation == "string-kinds":
        manifest["kinds"] = "service"
    elif mutation == "list-entrypoints":
        manifest["entryPoints"] = []
    elif mutation in ("absolute", "parent", "newline", "empty-path", "non-string-path"):
        manifest["entryPoints"]["overlay"] = {
            "absolute": str(root / "Overlay.qml"), "parent": "../Overlay.qml",
            "newline": "Overlay.qml\n", "empty-path": "", "non-string-path": None,
        }[mutation]
    elif mutation == "missing-file":
        (root / "Overlay.qml").unlink()
    elif mutation in ("missing-service", "missing-overlay"):
        del manifest["entryPoints"][mutation[8:]]
    elif mutation in ("missing-panel", "missing-bar-widget"):
        manifest["kinds"].append(mutation[8:])
    elif mutation == "symlink-file":
        (root / "linked").symlink_to(root / "Overlay.qml")
    elif mutation == "symlink-directory":
        (root / "linked").symlink_to(root / "lib", target_is_directory=True)
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(AssertionError):
        validate(root)


def test_versions_match():
    from omafindd import __version__

    manifest = json.loads((ROOT / "manifest.json").read_text())
    project = tomllib.loads((ROOT / "helper/pyproject.toml").read_text())
    assert manifest["version"] == project["project"]["version"] == __version__


@pytest.mark.parametrize("path", ["bin/omafind", "scripts/build-runtime.sh", "scripts/qmllint.sh"])
def test_executables_have_executable_index_mode(path):
    result = subprocess.run(
        ["git", "ls-files", "-s", path], cwd=ROOT, capture_output=True, text=True, check=True,
    )
    assert result.stdout.startswith("100755 "), f"{path} must be tracked with mode 100755"
