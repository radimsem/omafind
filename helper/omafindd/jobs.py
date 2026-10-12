import asyncio
import json
import multiprocessing
import os
import signal
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from .embedder import EmbeddingError, _parent_death_signal, document_text
from .embedding import Embedder, validated
from .extractors import ExtractionError, extract
from .store import Store


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
    def __init__(self, store: Store, embedder: Embedder, *, journal: Path):
        self.store, self.embedder, self.journal = store, embedder, journal
        self.queue = asyncio.Queue(maxsize=64)
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

    async def drain(self, *, only: list[int] | None = None, progress=lambda event: None):
        self.recover()
        selected = set(only) if only is not None else None
        started = False
        done = 0
        pool = _pool()
        try:
            while True:
                sql = "SELECT * FROM files WHERE state IN ('pending','partial')"
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
                for row in rows:
                    await self.queue.put(dict(row))
                for _ in range(min(64, len(rows))):
                    row = await self.queue.get()
                    file = row["id"]
                    info = json.loads(row["info"] or "{}")
                    append = row["state"] == "partial"
                    start = info.get("read_to", 0) + 1 if append else 1
                    try:
                        try:
                            future = pool.submit(
                                extract, self.store.mount / row["path"], row["kind"], start
                            )
                            result = await asyncio.wrap_future(future)
                        except BrokenProcessPool as error:
                            pool.shutdown(wait=True, cancel_futures=True)
                            pool = _pool()
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
                        if not started:
                            await self.embedder.start("full")
                            started = True
                        parts = [
                            segment.image
                            if segment.image is not None
                            else document_text(Path(row["path"]).name, segment.text)
                            for segment in result.segments
                        ]
                        vectors = []
                        for offset in range(0, len(parts), 16):
                            self._begin(file)
                            batch = parts[offset : offset + 16]
                            values = await self.embedder.embed_documents(batch)
                            if len(values) != len(batch):
                                raise ValueError("embedding precision fault")
                            vectors.extend(validated(value) for value in values)
                        self.store.write(
                            file,
                            result.segments,
                            vectors,
                            state=result.state,
                            info=result.info,
                            append=append,
                        )
                    except ExtractionError as error:
                        self.store.fail(file, str(error))
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
                        result = parts = batch = vectors = future = None
                        # Release the completed asyncio future before the next PNG window.
                        await asyncio.sleep(0)
                    self._committed(file)
                    self.queue.task_done()
                    done += 1
                    state = self.store.db.execute(
                        "SELECT state FROM files WHERE id=?", (file,)
                    ).fetchone()[0]
                    queued = self.store.db.execute(
                        "SELECT count(*) FROM files WHERE state IN ('pending','partial')"
                    ).fetchone()[0]
                    progress(
                        {
                            "done": done,
                            "queued": queued,
                            "volume": self.store.volume,
                            "state": state,
                        }
                    )
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
