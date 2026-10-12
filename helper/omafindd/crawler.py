import os
from pathlib import Path

from . import rules
from .store import Store


def crawl(store: Store, roots: list[dict], *, force=False) -> list[int]:
    candidates = {}
    for setting in roots:
        root = Path(setting["path"]).absolute()
        for candidate in rules.keep(
            rules.walk(root, excludes=setting.get("excludes", [])), root=root
        ):
            if isinstance(candidate, rules.Skip):
                continue
            try:
                stat = candidate.stat()
            except FileNotFoundError:
                continue
            relative = os.path.relpath(candidate, store.mount)
            candidates[relative] = (rules.classify(candidate), stat)
    scopes = [Path(os.path.abspath(root["path"])) for root in roots]
    existing = {
        row["path"]: row
        for row in store.db.execute("SELECT * FROM files")
        if any(
            Path(os.path.abspath(store.mount / row["path"])).is_relative_to(scope)
            for scope in scopes
        )
    }
    inodes = {(row["device"], row["inode"]): row for row in existing.values()}
    moved = set()
    queued = []
    with store.db:
        for path, (kind, stat) in candidates.items():
            row = existing.get(path)
            if row is None:
                match = inodes.get((stat.st_dev, stat.st_ino))
                if (
                    match is not None
                    and match["path"] not in candidates
                    and match["path"] not in moved
                    and match["size"] == stat.st_size
                    and match["mtime"] == stat.st_mtime
                    and match["kind"] == kind
                ):
                    store.move(match["id"], path)
                    moved.add(match["path"])
                    continue
            if row is None:
                file = store.db.execute(
                    "INSERT INTO files(path,kind,size,mtime,inode,device) VALUES(?,?,?,?,?,?)",
                    (path, kind, stat.st_size, stat.st_mtime, stat.st_ino, stat.st_dev),
                ).lastrowid
                store.name_row(file, path)
                queued.append(file)
            elif (
                force
                or row["size"] != stat.st_size
                or row["mtime"] != stat.st_mtime
                or row["inode"] != stat.st_ino
                or row["kind"] != kind
            ):
                store.db.execute(
                    "UPDATE files SET kind=?,size=?,mtime=?,inode=?,device=?,"
                    "state='pending',detail=NULL,info=NULL,indexed_at=NULL WHERE id=?",
                    (kind, stat.st_size, stat.st_mtime, stat.st_ino, stat.st_dev, row["id"]),
                )
                queued.append(row["id"])
        for path, row in existing.items():
            if path not in candidates and path not in moved:
                store.delete(row["id"])
    return queued
