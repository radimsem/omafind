import os
from pathlib import Path


def runtime_dir() -> Path:
    value = os.environ.get("XDG_RUNTIME_DIR")
    if not value:
        raise ValueError("XDG_RUNTIME_DIR is unset. Run omafindd in a user session.")
    return Path(value) / "omafind"


def socket_path() -> Path:
    return runtime_dir() / "ui.sock"


def preview_dir() -> Path:
    path = runtime_dir() / "preview"
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.parent.chmod(0o700)
    path.chmod(0o700)
    return path


def data_dir_path() -> Path:
    value = os.environ.get("XDG_DATA_HOME")
    base = Path(value) if value else Path.home() / ".local/share"
    return base / "omafind"


def data_dir() -> Path:
    path = data_dir_path()
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.chmod(0o700)
    return path


def runtime_bin() -> Path:
    return data_dir_path() / "runtime/bin/llama-server"


def model_dir() -> Path:
    return data_dir_path() / "model"


def manifest_path() -> Path:
    return Path.home() / ".config/omarchy/plugins/radimsem.omafind/manifest.json"


def shell_json_path() -> Path:
    return Path.home() / ".config/omarchy/shell.json"


def running_path() -> Path:
    return data_dir_path() / "running"


def journal_path() -> Path:
    return data_dir_path() / "journal"


def health_path() -> Path:
    return data_dir_path() / "index/health.json"


def thumbs_dir() -> Path:
    return data_dir_path() / "thumbs"
