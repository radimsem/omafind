import os
from dataclasses import dataclass
from pathlib import Path

from . import rules


@dataclass
class Reconciled:
    queued: list[int]
    deleted: int
    unchanged: int
    moved: int


def reconcile(store, roots: list[dict], *, only=None, force=False, skipped=None,
              progress=None) -> Reconciled:
    candidates, scopes = {}, []
    only = None if only is None else [Path(path).resolve() for path in only]
    for setting in roots:
        root = Path(setting['path']).expanduser().resolve()
        if not root.is_dir():
            continue
        found = {}
        try:
            for candidate in rules.keep(
                rules.walk(root, excludes=setting.get('excludes', []), only=only)
            ):
                if isinstance(candidate, rules.Skip):
                    if skipped is not None:
                        skipped[candidate.rule] += 1
                    continue
                try:
                    stat = candidate.stat()
                except FileNotFoundError:
                    continue
                found[os.path.relpath(candidate, store.mount)] = (rules.classify(candidate), stat)
        except OSError:
            if root.is_dir():
                raise
        # A vanished mount is not an empty tree.
        if root.is_dir():
            candidates.update(found)
            scopes.append(root)
    existing = {
        row['path']: row
        for row in store.db.execute('SELECT * FROM files')
        if any((store.mount / row['path']).resolve().is_relative_to(scope) for scope in scopes)
        and (only is None or any(
            (store.mount / row['path']).resolve().is_relative_to(scope) for scope in only))
    }
    inodes = {(row['device'], row['inode']): row for row in existing.values()}
    moved = set()
    result = Reconciled([], 0, 0, 0)
    total = len(candidates.keys() | existing.keys())
    done = 0

    def compared():
        nonlocal done
        done += 1
        if progress is not None:
            progress(done, total)

    with store.db:
        for path, (kind, stat) in candidates.items():
            row = existing.get(path)
            if row is None:
                match = inodes.get((stat.st_dev, stat.st_ino))
                if (match is not None and match['path'] not in candidates
                    and match['path'] not in moved and match['size'] == stat.st_size
                    and abs(match['mtime'] - stat.st_mtime) <= 0.001 and match['kind'] == kind):
                    store.move(match['id'], path)
                    moved.add(match['path'])
                    result.moved += 1
                    compared()
                    continue
            if row is None:
                file = store.db.execute(
                    'INSERT INTO files(path,kind,size,mtime,inode,device) VALUES(?,?,?,?,?,?)',
                    (path, kind, stat.st_size, stat.st_mtime, stat.st_ino, stat.st_dev),
                ).lastrowid
                store.name_row(file, path)
                result.queued.append(file)
            elif (force or row['size'] != stat.st_size
                  or abs(row['mtime'] - stat.st_mtime) > 0.001 or row['kind'] != kind):
                store.db.execute(
                    'UPDATE files SET kind=?,size=?,mtime=?,inode=?,device=?,'
                    "state='pending',detail=NULL,info=NULL,indexed_at=NULL WHERE id=?",
                    (kind, stat.st_size, stat.st_mtime, stat.st_ino, stat.st_dev, row['id']),
                )
                result.queued.append(row['id'])
            else:
                if row['inode'] != stat.st_ino or row['device'] != stat.st_dev:
                    store.db.execute('UPDATE files SET inode=?,device=? WHERE id=?',
                                     (stat.st_ino, stat.st_dev, row['id']))
                result.unchanged += 1
            compared()
        for path, row in existing.items():
            if path not in candidates:
                if path not in moved:
                    store.delete(row['id'])
                    result.deleted += 1
                compared()
    if progress is not None and total == 0:
        progress(0, 0)
    return result
