import json
import os
import re
import sqlite3
import subprocess
import time
from pathlib import Path

import numpy as np

from .models import REVISION
from .search_text import normalized

RUNTIME_TAG = "b11461"
SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE files(id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
 size INTEGER NOT NULL, mtime REAL NOT NULL, inode INTEGER NOT NULL, device INTEGER NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending', detail TEXT, info TEXT, indexed_at REAL);
CREATE INDEX files_inode ON files(device, inode);
CREATE INDEX files_state ON files(state, kind);
CREATE TABLE segments(id INTEGER PRIMARY KEY, file INTEGER NOT NULL
 REFERENCES files(id) ON DELETE CASCADE, kind TEXT NOT NULL, modality TEXT NOT NULL,
 loc REAL, loc_end REAL, excerpt TEXT, vec BLOB);
CREATE INDEX segments_file ON segments(file);
CREATE VIRTUAL TABLE fts USING fts5(name, body, original UNINDEXED,
 tokenize = "porter unicode61 remove_diacritics 2 categories 'L* N* Co M*'");
PRAGMA user_version = 5;
"""
CACHE_SCHEMA = """
CREATE INDEX IF NOT EXISTS segments_vector_ids ON segments(id) WHERE vec IS NOT NULL;
CREATE TRIGGER IF NOT EXISTS segments_deleted AFTER DELETE ON segments BEGIN
 INSERT INTO meta VALUES('segments_generation','1')
 ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1;
END;
CREATE TRIGGER IF NOT EXISTS segments_updated AFTER UPDATE ON segments BEGIN
 INSERT INTO meta VALUES('segments_generation','1')
 ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1;
END;
"""


def _unescape_target(target: str) -> str:
    return re.sub(
        r"\\x([0-9a-fA-F]{2})|\\([0-7]{3})",
        lambda match: chr(int(match[1], 16) if match[1] else int(match[2], 8)),
        target,
    )


def mounted_volumes(*, run=subprocess.run) -> dict[str, Path]:
    result = run(["findmnt", "-rno", "UUID,TARGET"], capture_output=True, text=True, check=True)
    mounts = {}
    devices = None
    for line in result.stdout.splitlines():
        fields = line.strip().split(maxsplit=1)
        if len(fields) == 2:
            uuid, target = fields[0], Path(_unescape_target(fields[1]))
        elif fields:
            target = Path(_unescape_target(fields[0]))
            if devices is None:
                devices = {}
                for entry in Path("/proc/self/mountinfo").read_text().splitlines():
                    parts = entry.split()
                    major, minor = map(int, parts[2].split(":"))
                    devices[Path(_unescape_target(parts[4]))] = f"dev-{os.makedev(major, minor)}"
            uuid = devices.get(target)
            if uuid is None:
                continue
        else:
            continue
        if uuid not in mounts or len(str(target)) < len(str(mounts[uuid])):
            mounts[uuid] = target
    home = run(["findmnt", "-no", "UUID,TARGET", "-T", str(Path.home())],
               capture_output=True, text=True)
    fields = home.stdout.strip().split(maxsplit=1)
    if home.returncode == 0 and len(fields) == 2:
        mounts[fields[0]] = Path(_unescape_target(fields[1]))
    return mounts


def volume_for(path: Path, *, run=subprocess.run, mounts=None) -> tuple[str, Path]:
    if mounts is None:
        mounts = mounted_volumes(run=run)
    result = run(["findmnt", "-no", "UUID,TARGET", "-T", str(path)], capture_output=True, text=True)
    fields = result.stdout.strip().split(maxsplit=1)
    if result.returncode == 0 and len(fields) == 2:
        uuid = fields[0]
        return uuid, mounts.get(uuid, Path(_unescape_target(fields[1])))
    if fields:
        target = Path(_unescape_target(fields[-1]))
        for uuid, mount in mounts.items():
            if mount == target:
                return uuid, mount
    stat = path.stat()
    for link in Path("/dev/disk/by-uuid").glob("*"):
        try:
            if link.stat().st_rdev == stat.st_dev:
                return link.name, mounts.get(link.name) or _mount_target(path, fields)
        except OSError:
            continue
    uuid = f"dev-{stat.st_dev}"
    return uuid, mounts.get(uuid) or _mount_target(path, fields)


def _mount_target(path: Path, fields: list[str]) -> Path:
    if fields:
        return Path(_unescape_target(fields[-1]))
    mount = path if path.is_dir() else path.parent
    while mount.parent != mount and mount.parent.stat().st_dev == mount.stat().st_dev:
        mount = mount.parent
    return mount


class Store:
    def __init__(
        self,
        path: Path,
        *,
        volume: str,
        mount: Path,
        label: str = "root",
        model_rev: str = REVISION,
        runtime_tag: str = RUNTIME_TAG,
    ):
        self.path, self.volume, self.mount, self.label = path, volume, mount, label
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        path.parent.chmod(0o700)
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        path.chmod(0o600)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            self.db.executescript(SCHEMA)
        elif version != 5:
            self.close()
            raise ValueError(f"Unsupported index schema: {version}")
        self.db.executescript(CACHE_SCHEMA)
        existing = dict(self.db.execute("SELECT key,value FROM meta"))
        with self.db:
            if existing and (
                existing.get("model_rev") != model_rev or existing.get("runtime_tag") != runtime_tag
            ):
                self.db.execute("UPDATE segments SET vec=NULL,modality='none'")
                self.db.execute("UPDATE files SET state='pending',detail=NULL,indexed_at=NULL")
            self.db.executemany(
                "INSERT OR REPLACE INTO meta VALUES(?,?)",
                [
                    ("model_rev", model_rev),
                    ("runtime_tag", runtime_tag),
                    ("volume_uuid", volume),
                    ("volume_label", label),
                ],
            )

    def close(self):
        self.db.close()

    def clear_segments(self, file: int, *, keeping_name=False):
        suffix = " AND kind != 'name'" if keeping_name else ""
        self.db.execute(
            f"DELETE FROM fts WHERE rowid IN (SELECT id FROM segments WHERE file=?{suffix})",
            (file,),
        )
        self.db.execute(f"DELETE FROM segments WHERE file=?{suffix}", (file,))

    def delete(self, file: int):
        self.clear_segments(file)
        self.db.execute("DELETE FROM files WHERE id=?", (file,))

    def name_row(self, file: int, path: str):
        row = self.db.execute(
            "INSERT INTO segments(file,kind,modality) VALUES(?,'name','none')", (file,)
        ).lastrowid
        self.db.execute(
            "INSERT INTO fts(rowid,name,body) VALUES(?,?,?)",
            (row, normalized(Path(path).name), normalized(" ".join(Path(path).parent.parts))),
        )

    def move(self, file: int, path: str):
        self.db.execute("UPDATE files SET path=? WHERE id=?", (path, file))
        self.db.execute(
            "UPDATE fts SET name=?,body=? WHERE rowid IN "
            "(SELECT id FROM segments WHERE file=? AND kind='name')",
            (normalized(Path(path).name), normalized(" ".join(Path(path).parent.parts)), file),
        )

    def write(self, file: int, segments, vectors, *, state: str, info: dict, append=False):
        if len(segments) != len(vectors):
            raise ValueError("embedding precision fault")
        with self.db:
            if not append:
                self.clear_segments(file, keeping_name=True)
            for segment, vector in zip(segments, vectors, strict=True):
                row = self.db.execute(
                    "INSERT INTO segments(file,kind,modality,loc,loc_end,excerpt,vec) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (
                        file,
                        segment.kind,
                        segment.modality,
                        segment.loc,
                        segment.loc_end,
                        segment.text[:400],
                        np.asarray(vector, dtype=np.float16).tobytes(),
                    ),
                ).lastrowid
                if segment.text:
                    body = normalized(segment.text)
                    self.db.execute(
                        "INSERT INTO fts(rowid,name,body,original) VALUES(?,'',?,?)",
                        (row, body, segment.text if body != segment.text else None),
                    )
            self.db.execute(
                "UPDATE files SET state=?,detail=NULL,info=?,indexed_at=? WHERE id=?",
                (state, json.dumps(info), time.time(), file),
            )

    def fail(self, file: int, detail: str):
        with self.db:
            self.clear_segments(file, keeping_name=True)
            self.db.execute("UPDATE files SET state='failed',detail=? WHERE id=?", (detail, file))

    @classmethod
    def open_existing(cls, path: Path, mount: Path):
        store = cls.__new__(cls)
        store.path, store.mount = path, mount
        store.db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            store.db.row_factory = sqlite3.Row
            meta = dict(store.db.execute("SELECT key,value FROM meta"))
            store.volume, store.label = meta["volume_uuid"], meta["volume_label"]
        except BaseException:
            store.close()
            raise
        return store
