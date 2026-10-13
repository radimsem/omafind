import fcntl
import json
import os
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path

from .code import index_code
from .crawler import crawl
from .jobs import Jobs
from .store import Store, volume_for


async def reindex(
    roots: list[dict],
    *,
    directory: Path,
    embedder,
    volume: str | None = None,
    volume_resolver=volume_for,
    progress=None,
    settings=None,
    code_roots: Sequence[Path] = (),
    force=True,
):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    descriptor = os.open(directory / "index.lock", os.O_CREAT | os.O_RDWR, 0o600)
    stores = []
    skipped = Counter()
    started = time.time()
    intent = os.open(directory / "index.want", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "w") as lock, os.fdopen(intent, "w") as want:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("waiting index.lock", file=sys.stderr)
            fcntl.flock(want, fcntl.LOCK_EX)
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            groups, mounts = defaultdict(list), {}
            for root in roots:
                path = Path(root["path"]).expanduser().absolute()
                uuid, mount = volume_resolver(path)
                if volume is None or uuid == volume:
                    groups[uuid].append(dict(root, path=str(path)))
                    mounts[uuid] = mount
            if volume is not None and not groups:
                raise ValueError(f"No selected root is on volume {volume}")
            for uuid, selected in groups.items():
                store = Store(
                    directory / "index" / f"{uuid}.sqlite", volume=uuid, mount=mounts[uuid]
                )
                stores.append(store)
                crawl(store, selected, force=force, skipped=skipped)
            index_dir = directory / "index"
            index_dir.mkdir(mode=0o700, exist_ok=True)
            temporary = index_dir / "run.json.tmp"
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                json.dump({"pid": os.getpid(), "started": started,
                           "skipped": dict(skipped)}, stream)
            temporary.replace(index_dir / "run.json")
            for store in stores:
                jobs = Jobs(store, embedder, journal=directory / "journal", settings=settings)
                await jobs.drain(progress=progress or _progress)
            if code_roots:
                await index_code(code_roots, directory / "index", embedder)
            print("queued 0", file=sys.stderr)
        finally:
            await embedder.stop()
            for store in stores:
                store.close()


def _progress(event):
    print(
        f"done {event['done']} queued {event['queued']} volume {event['volume']}", file=sys.stderr
    )
