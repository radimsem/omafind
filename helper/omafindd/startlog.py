"""The last fatal daemon start failure, kept so the UI can offer "Open log" while it is down."""

import os
import time

from . import paths

NAME = "omafindd-start.log"


def write(text: str) -> None:
    """Replace the start log with `text`. Never raises: it runs while the daemon is failing."""
    try:
        path = paths.logs_dir() / NAME
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text.rstrip()}\n")
    except OSError:
        pass


def clear() -> None:
    try:
        (paths.logs_dir() / NAME).unlink(missing_ok=True)
    except OSError:
        pass
