import fcntl
import os
import sys
from collections import defaultdict
from pathlib import Path

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
):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    descriptor = os.open(directory / "index.lock", os.O_CREAT | os.O_RDWR, 0o600)
    stores = []
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
                crawl(store, selected, force=True)
                jobs = Jobs(store, embedder, journal=directory / "journal", settings=settings)
                await jobs.drain(progress=progress or _progress)
            print("queued 0", file=sys.stderr)
        finally:
            await embedder.stop()
            for store in stores:
                store.close()


def _progress(event):
    print(
        f"done {event['done']} queued {event['queued']} volume {event['volume']}", file=sys.stderr
    )
