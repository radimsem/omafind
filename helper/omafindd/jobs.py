import asyncio
import base64
import json
import logging
import multiprocessing
import os
import signal
import subprocess
import sys
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from .embedder import (
    EmbeddingError,
    EmbeddingRejected,
    InputAudio,
    _parent_death_signal,
    document_text,
)
from .embedding import Embedder, validated
from .extractors import ExtractionError, extract
from .settings import Settings
from .store import Store

logger = logging.getLogger(__name__)


def _worker(parent):
    if sys.platform == "linux":
        _parent_death_signal(parent, signal.SIGKILL)
    os.nice(19)
    try:
        subprocess.run(
            ["ionice", "-c", "3", "-p", str(os.getpid())], capture_output=True, check=False
        )
    except OSError:
        pass


def _pool():
    return ProcessPoolExecutor(
        max_workers=1, initializer=_worker, initargs=(os.getpid(),),
        mp_context=multiprocessing.get_context("spawn")
    )


class Jobs:
    def __init__(self, store: Store, embedder: Embedder, *, journal: Path, settings=None,
                 pause=None):
        self.store, self.embedder, self.journal = store, embedder, journal
        self.settings = settings or Settings()
        self.pause = pause
        self.batch = 0

    def _records(self):
        if not self.journal.exists():
            return []
        return [json.loads(line) for line in self.journal.read_text().splitlines() if line]

    def recover(self) -> list[int]:
        ids = list(
            dict.fromkeys(
                file
                for record in self._records()
                if record["volume"] == self.store.volume
                for file in record["files"]
            )
        )
        active = []
        with self.store.db:
            for file in ids:
                if (
                    self.store.db.execute("SELECT 1 FROM files WHERE id=?", (file,)).fetchone()
                    is None
                ):
                    self._committed(file)
                    continue
                active.append(file)
                self.store.db.execute(
                    "UPDATE files SET state='pending' WHERE id=? AND state='done'", (file,)
                )
        return active

    def _begin(self, file):
        self.journal.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.batch += 1
        descriptor = os.open(self.journal, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(
                json.dumps({"b": self.batch, "volume": self.store.volume, "files": [file]}) + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())

    def _committed(self, file):
        records = []
        for record in self._records():
            if record["volume"] == self.store.volume:
                record["files"] = [value for value in record["files"] if value != file]
            if record["files"]:
                records.append(record)
        temporary = self.journal.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.writelines(json.dumps(record) + "\n" for record in records)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.journal)

    async def drain(self, *, only: list[int] | None = None, progress=lambda event: None,
                    prefetch: int = 4):
        self.recover()
        selected = set(only) if only is not None else None
        started = False
        done = 0
        pool = _pool()
        try:
            while True:
                sql = ("SELECT * FROM files WHERE "
                       "(state='pending' OR (state='partial' AND detail IS NULL))")
                params = []
                if selected is not None:
                    if not selected:
                        break
                    sql += " AND id IN (" + ",".join("?" for _ in selected) + ")"
                    params = list(selected)
                rows = list(
                    self.store.db.execute(
                        sql + " ORDER BY state='partial',mtime DESC,id LIMIT 64", params
                    )
                )
                if not rows:
                    break
                pending = {}

                def submit(row, pool, pending=pending):
                    info = json.loads(row["info"] or "{}")
                    append = row["state"] == "partial" and row["detail"] is None
                    start = (info.get("read_to", 0) if row["kind"] == "pdf"
                             else info.get("audio_next", 0)) + 1 if append else 1
                    args = [self.store.mount / row["path"], row["kind"], start]
                    if row["kind"] in ("image", "video", "audio"):
                        args.extend([self.settings.audio, self.settings.image_budget])
                    if row["kind"] == "video":
                        args.append(info.get("frame_next") if append else 0.0)
                    try:
                        future = pool.submit(extract, *args)
                    except Exception as error:
                        future = Future()
                        future.set_exception(error)
                    pending[row["id"]] = (future, info, append)

                ordered = [dict(row) for row in rows]
                for row in ordered[:prefetch]:
                    submit(row, pool)
                for index, row in enumerate(ordered):
                    file = row["id"]
                    future, info, append = pending.pop(file)
                    try:
                        try:
                            result = await asyncio.wrap_future(future)
                        except BrokenProcessPool as error:
                            pool.shutdown(wait=True, cancel_futures=True)
                            pool = _pool()
                            for queued in ordered[index + 1:index + prefetch]:
                                submit(queued, pool)
                            raise ExtractionError("extract-failed") from error
                        except Exception as error:
                            detail = "extract-failed"
                            if isinstance(error, subprocess.TimeoutExpired):
                                detail = "timeout"
                            elif isinstance(error, ExtractionError) and str(error) in (
                                "encrypted-pdf", "timeout"
                            ):
                                detail = str(error)
                            raise ExtractionError(detail) from error
                        if result.segments and not started:
                            await self.embedder.start("full")
                            started = True
                        segments = result.segments
                        vectors = []
                        groups = [segments]
                        if row["kind"] == "video":
                            groups = [[s for s in segments if s.audio is None],
                                      [s for s in segments if s.audio is not None]]
                            segments = []
                        for group in groups:
                            group_vectors = []
                            try:
                                for offset in range(0, len(group), 16):
                                    if self.pause is not None:
                                        await self.pause()
                                    self._begin(file)
                                    batch = [
                                        segment.image if segment.image is not None
                                        else InputAudio(base64.b64encode(segment.audio).decode())
                                        if segment.audio is not None
                                        else document_text(Path(row["path"]).name, segment.text)
                                        for segment in group[offset:offset + 16]
                                    ]
                                    values = await self.embedder.embed_documents(batch)
                                    if len(values) != len(batch):
                                        raise ValueError("embedding precision fault")
                                    group_vectors.extend(validated(value) for value in values)
                            except (ValueError, EmbeddingError) as error:
                                if row["kind"] != "video" or not group or (
                                    group[0].audio is None or (not vectors and not append)
                                ):
                                    raise
                                result.state = "partial"
                                result.detail = (
                                    "embedding precision fault" if isinstance(error, ValueError)
                                    or str(error) == "embedding precision fault"
                                    else "soundtrack embedding failed"
                                )
                                break
                            vectors.extend(group_vectors)
                            if row["kind"] == "video":
                                segments.extend(group)
                        if result.thumbnail is not None:
                            result.info["thumb"] = self.store.thumbnail(file, result.thumbnail)
                        if append:
                            info.pop("frame_next", None)
                            info.pop("audio_next", None)
                            info.update(result.info)
                            result.info = info
                        self.store.write(
                            file,
                            segments,
                            vectors,
                            state=result.state,
                            info=result.info,
                            append=append,
                            ocr_text=result.ocr_text,
                            detail=result.detail,
                        )
                    except ExtractionError as error:
                        self.store.fail(file, str(error))
                    except EmbeddingRejected as error:
                        logger.warning("Embedding rejected file %s (%s)", file, error)
                        if append:
                            self.store.halt(file, "embedding-failed")
                        else:
                            self.store.fail(file, "embedding-failed")
                    except EmbeddingError as error:
                        if str(error) != "embedding precision fault":
                            raise
                        self.store.fail(file, "embedding precision fault")
                    except Exception as error:
                        self.store.fail(
                            file,
                            "embedding precision fault"
                            if isinstance(error, ValueError)
                            and str(error) == "embedding precision fault"
                            else "extract-failed",
                        )
                    finally:
                        result = batch = vectors = future = segments = groups = group = None
                        group_vectors = values = None
                        # Release the completed asyncio future before the next PNG window.
                        await asyncio.sleep(0)
                    self._committed(file)
                    done += 1
                    state = self.store.db.execute(
                        "SELECT state FROM files WHERE id=?", (file,)
                    ).fetchone()[0]
                    queued = self.store.db.execute(
                        "SELECT count(*) FROM files WHERE state='pending' "
                        "OR (state='partial' AND detail IS NULL)"
                    ).fetchone()[0]
                    progress(
                        {
                            "done": done,
                            "queued": queued,
                            "volume": self.store.volume,
                            "state": state,
                        }
                    )
                    if index + prefetch < len(ordered):
                        submit(ordered[index + prefetch], pool)
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
