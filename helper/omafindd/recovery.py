import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StartState:
    clean: bool
    journal_files: int


def begin(data_dir: Path) -> StartState:
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    running = data_dir / 'running'
    clean = not running.exists()
    journal = data_dir / 'journal'
    files = set()
    if journal.exists():
        for line in journal.read_text().splitlines():
            if line:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                files.update((record['volume'], file) for file in record['files'])
    descriptor = os.open(running, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return StartState(clean, len(files))


def end(data_dir: Path) -> None:
    (data_dir / 'running').unlink(missing_ok=True)
