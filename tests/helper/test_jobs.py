import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import weakref
import zlib
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fakes.embedder import FakeEmbedder
from omafindd.crawler import crawl
from omafindd.extractors import ExtractionError
from omafindd.store import Store
from support.corpus import pdf


@pytest.fixture
def inline_pool(monkeypatch):
    from omafindd import jobs

    class Pool:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.shutdown()

        def shutdown(self, **kwargs):
            pass

        def submit(self, function, *args):
            future = Future()
            try:
                future.set_result(function(*args))
            except Exception as error:
                future.set_exception(error)
            return future

    monkeypatch.setattr(jobs, "ProcessPoolExecutor", Pool)
    return Pool


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "index/v.sqlite", volume="v", mount=tmp_path)
    yield value
    value.close()


async def test_fake_word_overlap_increases_cosine():
    embedder = FakeEmbedder()
    query = await embedder.embed_query("lunar eclipse")
    a, b = await embedder.embed_documents(["lunar eclipse telescope", "sourdough flour bread"])
    assert query @ a > query @ b
    assert np.linalg.norm(a.astype(np.float32)) == pytest.approx(1, abs=0.001)


async def test_crash_journal_retries_only_inflight_file(store, tmp_path):
    from omafindd.jobs import Jobs

    for name in ("one.txt", "two.txt"):
        (tmp_path / name).write_text("lunar eclipse")
    crawl(store, [{"path": str(tmp_path), "excludes": []}])
    first, second = [r[0] for r in store.db.execute("SELECT id FROM files ORDER BY path")]
    journal = tmp_path / "journal"

    class Crash(FakeEmbedder):
        async def embed_documents(self, parts):
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await Jobs(store, Crash(), journal=journal).drain(only=[first])
    record = json.loads(journal.read_text())
    assert record["files"] == [first]
    assert record["volume"] == "v"
    assert journal.stat().st_mode & 0o777 == 0o600
    recovered = Jobs(store, FakeEmbedder(), journal=journal)
    assert recovered.recover() == [first]
    await recovered.drain(only=[first])
    assert store.db.execute("SELECT state FROM files WHERE id=?", (first,)).fetchone()[0] == "done"
    assert (
        store.db.execute("SELECT state FROM files WHERE id=?", (second,)).fetchone()[0] == "pending"
    )
    assert journal.read_text() == ""


async def test_nan_vector_fails_file(store, tmp_path):
    from omafindd.jobs import Jobs

    (tmp_path / "one.txt").write_text("fixture")
    crawl(store, [{"path": str(tmp_path), "excludes": []}])

    class Invalid(FakeEmbedder):
        async def embed_documents(self, parts):
            return [np.full(768, np.nan) for _ in parts]

    await Jobs(store, Invalid(), journal=tmp_path / "journal").drain()
    assert tuple(store.db.execute("SELECT state,detail FROM files").fetchone()) == (
        "failed",
        "embedding precision fault",
    )
    assert store.db.execute("SELECT count(*) FROM segments WHERE kind!='name'").fetchone()[0] == 0


async def test_batches_are_at_most_16_and_file_is_atomic(store, tmp_path):
    from omafindd.jobs import Jobs

    (tmp_path / "many.txt").write_text("lunar eclipse " * 4000)
    crawl(store, [{"path": str(tmp_path), "excludes": []}])

    class Observe(FakeEmbedder):
        sizes = []

        async def embed_documents(self, parts):
            self.sizes.append(len(parts))
            assert (
                store.db.execute("SELECT count(*) FROM segments WHERE kind!='name'").fetchone()[0]
                == 0
            )
            return await super().embed_documents(parts)

    embedder = Observe()
    jobs = Jobs(store, embedder, journal=tmp_path / "journal")
    assert jobs.queue.maxsize == 64
    await jobs.drain()
    assert len(embedder.sizes) > 1 and max(embedder.sizes) <= 16
    assert store.db.execute("SELECT state FROM files").fetchone()[0] == "done"


async def test_long_pdf_finishes_after_pending_files(store, tmp_path):
    from omafindd.jobs import Jobs

    pdf(tmp_path / "long.pdf", ["lunar eclipse " * 30] * 60)
    (tmp_path / "one.txt").write_text("sourdough")
    crawl(store, [{"path": str(tmp_path), "excludes": []}])
    progress = []
    await Jobs(store, FakeEmbedder(), journal=tmp_path / "journal").drain(
        progress=lambda event: progress.append(event)
    )
    states = [(p["state"], p["queued"]) for p in progress]
    assert any(state == "partial" for state, _ in states)
    assert states[-1] == ("done", 0)
    assert store.db.execute("SELECT count(*) FROM segments WHERE kind='page'").fetchone()[0] == 60


async def test_40_page_pdf_is_done_in_one_indexing_pass(store, tmp_path, inline_pool):
    from omafindd.jobs import Jobs

    pdf(tmp_path / "short.pdf", ["lunar eclipse research " * 25] * 40)
    crawl(store, [{"path": str(tmp_path)}])
    progress = []
    await Jobs(store, FakeEmbedder(), journal=tmp_path / "journal").drain(progress=progress.append)
    assert [(event["state"], event["queued"]) for event in progress] == [("done", 0)]
    assert store.db.execute("SELECT state FROM files").fetchone()[0] == "done"
    assert store.db.execute("SELECT count(*) FROM segments WHERE kind='page'").fetchone()[0] == 40


async def test_embedder_adapter_uses_protocol_prompts_and_images():
    from omafindd.embedding import Adapter
    from omafindd.extractors import ImagePart

    class Runtime(FakeEmbedder):
        received = []

        async def embed(self, parts):
            self.received.extend(parts)
            return await super().embed(parts)

    runtime = Runtime()
    adapter = Adapter(runtime)
    await adapter.embed_query("hello")
    await adapter.embed_documents(["title: a.txt | text: hello", ImagePart(b"png", 48, 48)])
    assert runtime.received[0].text == "task: search result | query: hello"
    assert runtime.received[1].text == "title: a.txt | text: hello"
    assert runtime.received[2].url == "data:image/png;base64,cG5n"


async def test_runtime_precision_fault_fails_file(store, tmp_path):
    from omafindd.embedder import EmbeddingError
    from omafindd.jobs import Jobs

    (tmp_path / "a.txt").write_text("fixture")
    crawl(store, [{"path": str(tmp_path), "excludes": []}])

    class Invalid(FakeEmbedder):
        async def embed_documents(self, parts):
            raise EmbeddingError("embedding precision fault")

    await Jobs(store, Invalid(), journal=tmp_path / "journal").drain()
    assert tuple(store.db.execute("SELECT state,detail FROM files").fetchone()) == (
        "failed",
        "embedding precision fault",
    )


def test_recovery_discards_journal_ids_deleted_by_crawl(store, tmp_path):
    from omafindd.jobs import Jobs

    journal = tmp_path / "journal"
    journal.write_text('{"b":1,"volume":"v","files":[41]}\n')
    jobs = Jobs(store, FakeEmbedder(), journal=journal)
    assert jobs.recover() == []
    assert journal.read_text() == ""


async def test_invalid_office_member_fails_only_its_file(store, tmp_path):
    import zipfile

    from omafindd.jobs import Jobs

    with zipfile.ZipFile(tmp_path / "broken.docx", "w") as archive:
        archive.writestr("other.xml", "fixture")
    (tmp_path / "good.txt").write_text("lunar eclipse")
    crawl(store, [{"path": str(tmp_path), "excludes": []}])
    await Jobs(store, FakeEmbedder(), journal=tmp_path / "journal").drain()
    states = dict(store.db.execute("SELECT path,state FROM files"))
    assert states == {"broken.docx": "failed", "good.txt": "done"}


@pytest.mark.parametrize(
    "error,detail",
    [
        (zlib.error("fixture"), "extract-failed"),
        (NotImplementedError("fixture"), "extract-failed"),
        (RuntimeError("fixture"), "extract-failed"),
        (ValueError("bad image dimensions"), "extract-failed"),
        (subprocess.TimeoutExpired("pdfinfo", 60), "timeout"),
        (ExtractionError("timeout"), "timeout"),
        (ExtractionError("encrypted-pdf"), "encrypted-pdf"),
        (ExtractionError("pdftoppm failed"), "extract-failed"),
    ],
)
async def test_poison_file_does_not_abort_or_remain_pending(
    store, tmp_path, monkeypatch, inline_pool, error, detail
):
    from omafindd import jobs

    for name in ("broken.txt", "good.txt"):
        (tmp_path / name).write_text("lunar eclipse")
    crawl(store, [{"path": str(tmp_path)}])
    extract = jobs.extract

    def poison(path, *args):
        if path.name == "broken.txt":
            raise error
        return extract(path, *args)

    monkeypatch.setattr(jobs, "extract", poison)
    progress = []
    runner = jobs.Jobs(store, FakeEmbedder(), journal=tmp_path / "journal")
    await runner.drain(progress=progress.append)
    assert [tuple(row) for row in store.db.execute(
        "SELECT path,state,detail FROM files ORDER BY path"
    )] == [("broken.txt", "failed", detail), ("good.txt", "done", None)]
    assert progress[-1]["queued"] == 0
    assert runner.journal.read_text() == ""
    await runner.drain(progress=lambda event: pytest.fail("failed file was requeued"))


async def test_broken_pool_is_rebuilt_for_remaining_files(
    store, tmp_path, monkeypatch, inline_pool
):
    from omafindd import jobs

    for name in ("one.txt", "two.txt", "three.txt"):
        (tmp_path / name).write_text("lunar eclipse")
    crawl(store, [{"path": str(tmp_path)}])
    pools = []

    class Pool(inline_pool):
        def __init__(self, **kwargs):
            pools.append(self)

        def submit(self, function, *args):
            if self is pools[0]:
                future = Future()
                future.set_exception(BrokenProcessPool("fixture worker died"))
                return future
            return super().submit(function, *args)

    monkeypatch.setattr(jobs, "ProcessPoolExecutor", Pool)
    await jobs.Jobs(store, FakeEmbedder(), journal=tmp_path / "journal").drain()
    assert len(pools) == 2
    assert dict(store.db.execute("SELECT state,count(*) FROM files GROUP BY state")) == {
        "done": 2, "failed": 1
    }
    detail = store.db.execute("SELECT detail FROM files WHERE state='failed'").fetchone()[0]
    assert detail == "extract-failed"


async def test_nonprecision_embedding_error_still_propagates(store, tmp_path, inline_pool):
    from omafindd.embedder import EmbeddingError
    from omafindd.jobs import Jobs

    (tmp_path / "a.txt").write_text("fixture")
    crawl(store, [{"path": str(tmp_path)}])

    class Failed(FakeEmbedder):
        async def embed_documents(self, parts):
            raise EmbeddingError("server unavailable")

    with pytest.raises(EmbeddingError, match="server unavailable"):
        await Jobs(store, Failed(), journal=tmp_path / "journal").drain()


async def test_pdf_windows_are_committed_before_next_extraction(
    store, tmp_path, monkeypatch, inline_pool
):
    from omafindd import jobs
    from omafindd.extractors import Extracted, ImagePart, Segment

    (tmp_path / "long.pdf").write_text("fixture")
    crawl(store, [{"path": str(tmp_path)}])
    positions = []
    images = []

    def window(path, kind, start):
        positions.append(start)
        assert all(image() is None for image in images), "previous PNG window is still resident"
        count = store.db.execute(
            "SELECT count(*) FROM segments WHERE kind='page_image'"
        ).fetchone()[0]
        assert count == start - 1
        end = min(95, 30 if start == 1 else start + 31)
        segments = [Segment("page_image", "image", loc=page, image=ImagePart(b"png", 48, 48))
                    for page in range(start, end + 1)]
        images.extend(weakref.ref(segment.image) for segment in segments)
        return Extracted(
            segments,
            {"pages": 95, "read_to": end},
            "partial" if end < 95 else "done",
        )

    monkeypatch.setattr(jobs, "extract", window)
    await jobs.Jobs(store, FakeEmbedder(), journal=tmp_path / "journal").drain()
    assert positions == [1, 31, 63, 95]
    assert store.db.execute("SELECT state FROM files").fetchone()[0] == "done"
    pages = store.db.execute("SELECT loc FROM segments WHERE kind='page_image' ORDER BY loc")
    assert [row[0] for row in pages] == list(range(1, 96))


@pytest.mark.parametrize("current_parent", [41, 42])
def test_worker_sets_parent_death_sigkill_and_checks_race(monkeypatch, current_parent):
    import ctypes

    from omafindd.jobs import _worker

    calls, killed = [], []
    monkeypatch.setattr(ctypes, "CDLL", lambda *args, **kwargs: SimpleNamespace(
        prctl=lambda *args: calls.append(args) or 0
    ))
    monkeypatch.setattr(os, "getppid", lambda: current_parent)
    monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(os, "nice", lambda value: None)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: None)
    _worker(41)
    assert calls == [(1, signal.SIGKILL, 0, 0, 0)]
    assert killed == ([(os.getpid(), signal.SIGKILL)] if current_parent != 41 else [])


def test_pool_worker_and_tracker_exit_after_parent_is_killed():
    def alive(pid):
        try:
            return Path(f"/proc/{pid}/stat").read_text().split(")", 1)[1].split()[0] != "Z"
        except FileNotFoundError:
            return False

    script = Path(__file__).parents[1] / "support/pool_parent.py"
    env = {**os.environ, "PYTHONPATH": str(script.parents[2] / "helper")}
    children = []
    with subprocess.Popen(
        [sys.executable, str(script)], env=env, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    ) as parent:
        try:
            children = json.loads(parent.stdout.readline())
            assert len(children) == 2 and all(alive(pid) for pid in children)
            parent.kill()
            parent.wait(timeout=2)
            for _ in range(200):
                if not any(alive(pid) for pid in children):
                    break
                time.sleep(0.01)
            assert not any(alive(pid) for pid in children), "pool child survived SIGKILL of reindex"
        finally:
            if parent.poll() is None:
                parent.kill()
            for pid in children:
                if alive(pid):
                    os.kill(pid, signal.SIGKILL)


async def test_extraction_await_uses_future_completion_and_can_cancel(
    store, tmp_path, monkeypatch, inline_pool
):
    from omafindd import jobs

    (tmp_path / "one.txt").write_text("lunar eclipse")
    crawl(store, [{"path": str(tmp_path)}])
    future = Future()
    entered = asyncio.Event()

    class Pool(inline_pool):
        def submit(self, *args):
            entered.set()
            return future

    monkeypatch.setattr(jobs, "ProcessPoolExecutor", Pool)
    pending = asyncio.create_task(jobs.Jobs(
        store, FakeEmbedder(), journal=tmp_path / "journal"
    ).drain())
    try:
        await entered.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert future.cancelled()
        assert store.db.execute("SELECT state FROM files").fetchone()[0] == "pending"
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


async def test_rejected_file_fails_and_the_run_continues(store, tmp_path, inline_pool, caplog):
    from omafindd.embedder import EmbeddingRejected
    from omafindd.jobs import Jobs

    (tmp_path / "bad.txt").write_text("reject me")
    (tmp_path / "good.txt").write_text("keep me")
    crawl(store, [{"path": str(tmp_path)}])

    class Picky(FakeEmbedder):
        async def embed_documents(self, parts):
            if any("reject" in part for part in parts if isinstance(part, str)):
                raise EmbeddingRejected("HTTP 500: input (3359 tokens) is too large")
            return await super().embed_documents(parts)

    await Jobs(store, Picky(), journal=tmp_path / "journal").drain()
    states = dict(store.db.execute(
        "SELECT path, state || ':' || coalesce(detail, '') FROM files"))
    assert states == {"bad.txt": "failed:embedding-failed", "good.txt": "done:"}
    assert "HTTP 500" in caplog.text and "reject me" not in caplog.text


async def test_rejected_pdf_window_keeps_earlier_pages(store, tmp_path, monkeypatch, inline_pool):
    from omafindd import jobs
    from omafindd.embedder import EmbeddingRejected
    from omafindd.extractors import Extracted, Segment

    (tmp_path / "long.pdf").write_text("fixture")
    crawl(store, [{"path": str(tmp_path)}])

    def window(path, kind, start):
        end = 30 if start == 1 else 58
        segments = [Segment("page", "text", f"page {page}", loc=page, loc_end=page)
                    for page in range(start, end + 1)]
        return Extracted(segments, {"pages": 58, "read_to": end},
                         "partial" if end < 58 else "done")

    class Second(FakeEmbedder):
        async def embed_documents(self, parts):
            if any("page 31" in part for part in parts):
                raise EmbeddingRejected("HTTP 500: too large")
            return await super().embed_documents(parts)

    monkeypatch.setattr(jobs, "extract", window)
    await jobs.Jobs(store, Second(), journal=tmp_path / "journal").drain()
    row = store.db.execute("SELECT state, detail FROM files").fetchone()
    assert tuple(row) == ("partial", "embedding-failed")
    assert store.db.execute("SELECT count(*) FROM segments WHERE kind='page'").fetchone()[0] == 30
