import hashlib
import json
from pathlib import Path


def fingerprint(root: Path) -> str:
    """Return `<manifest version>+<12 hex>` for the daemon code and lock under plugin `root`.

    Raises OSError for an unreadable file and ValueError for a manifest without a version.
    Stdlib only: bin/omafind runs it with the system Python before the venv exists.
    """
    version = json.loads((root / "manifest.json").read_text()).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"{root / 'manifest.json'} has no version")
    helper = root / "helper"
    files = [helper / "uv.lock", helper / "pyproject.toml",
             *sorted((helper / "omafindd").rglob("*.py"))]
    digest = hashlib.sha256()
    for path in files:
        data = path.read_bytes()
        digest.update(f"{path.relative_to(root).as_posix()}\0{len(data)}\0".encode() + data)
    return f"{version}+{digest.hexdigest()[:12]}"
