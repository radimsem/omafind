# Indexing, Search and Setup Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the ten v1 problems found on 2026-10-15: one inotify instance for the watcher, no indexing run killed by one file, faster indexing, `code:` that works by default, a meaning leg that always fires, Neovim opening on the line, smooth and sharp previews, and a Folders step that sorts by size and leaves worktrees out.

**Architecture:** Daemon fixes stay inside their modules (`watcher.py` plus a new `inotify.py`, `extractors.py`, `embedder.py`, `jobs.py`, `service.py`, `search_code.py`, `discovery.py`, `preview.py`, `opener.py`). QML changes stay in their components (`SearchView.qml`, `PreviewPane.qml`, `PreviewLayer.qml`, `FolderTree.qml`, `SetupFolders.qml`, `RuleTag.qml`, `Service.qml`), with the logic in testable `lib/*.js` functions. One message field changes on the wire (`discover_counts.repos`/`.worktrees`, `results.notice`); settings keep their shape.

**Tech Stack:** Python 3.12 (`uv`, pytest, pytest-asyncio, ruff), `inotify_simple`, QML on Quickshell (Qt 6.11), plain JS with `node --test`.

**Spec:** `docs/superpowers/specs/2026-10-15-indexing-search-setup-polish-design.md`

## Global Constraints

- Work only in the worktree `~/personal/projects/omafind-wt/indexing-search-setup-polish` on branch `fix/indexing-search-setup-polish`. Never commit on `main`.
- Commits: one `-m`, Conventional Commits subject only, at most 72 characters, no body, no trailers, signed (`git commit -S -m '…'`, key `01B91D1C3DA525DF`). Stage exact paths; never stage `.superpowers/` or `.pytest_cache`.
- Never `push --force`, `reset --hard`, `clean` or `branch -D`. Do not push or open a PR; the owner asks for that.
- Heavy jobs (llama-server, `bin/omafind reindex`, the dev daemon with a model, timing runs) run one at a time inside `systemd-run --user --scope --quiet --collect -p MemoryMax=8G -p MemorySwapMax=0 -- <command>`. Stop every `llama-server` you start; `pgrep -x llama-server` must list only the live daemon's server (its parent is the `omafind.service` PID) when you finish.
- Never touch the live `omafind.service`, `~/.config` or `~/.config/omarchy/shell.json`. Never drive the live overlay with `wtype` or key injection. Never `pkill -f` a pattern from the same Bash call that names it. Repointing the live plugin is done by the owner.
- Copy: sentence case, straight quotes, no em or en dashes in prose, no exclamation marks. Status text is fact tokens, not prose. Errors say what happened, why, then what to do next.
- Comments only where code cannot say it (`~/.agents/rules/comments.md`). Match the surrounding style.
- `docs/ipc.md` owns socket messages; any message change updates it in the same PR. Read `docs/DESIGN.md` before touching QML.
- Checks, run from the worktree:
  - `uv run --project helper pytest -q`
  - `node --test "tests/js/*.test.mjs"`
  - `uv run --project helper ruff check helper tests bin/omafind scripts evals`
  - `scripts/qmllint.sh`

## Review Focus

1. A directory renamed inside a watched root: the old subtree's watches go away and the new path is watched. Pinned in Task 1 (`test_renamed_directory_moves_its_watches`).
2. inotify reuses a watch descriptor after `IN_IGNORED`: unscheduling a stale watch must not drop the new directory's watch. Pinned in Task 1 (`test_stale_watch_does_not_remove_reused_descriptor`).
3. A repository inside a worktree, a dataset or a skipped folder never gets Code by default. Pinned in Task 8 (`repos inside skipped folders or worktrees are not offered code`).
4. A dense page (math or CJK) whose characters are fewer than the old cap but whose tokens are more: it must still split. Pinned in Task 2 (`test_dense_text_splits_below_token_cap`).
5. Switching selection three times inside the 150 ms fade gate: the last selection is the one shown. Pinned in Task 9 (`rapid switches show the last selection`).

---

### Task 1: Watcher on one inotify instance

**Files:**
- Create: `helper/omafindd/inotify.py`
- Modify: `helper/omafindd/watcher.py`, `helper/omafindd/__main__.py` (no change needed unless the message test names the package), `helper/pyproject.toml`, `helper/uv.lock`
- Test: `tests/helper/test_watcher.py`, `tests/helper/test_inotify.py` (new), `tests/helper/test_update.py:59-67`

**Interfaces:**
- Produces: `omafindd.inotify.InotifyObserver` with `schedule(handler, path, *, recursive=False) -> Watch`, `unschedule(watch)`, `unschedule_all()`, `start()`, `stop()`, `join()`, attribute `on_overflow: Callable[[], None]`. `omafindd.inotify.Event(event_type, src_path, is_directory, dest_path="")`. `Watch(wd: int, path: str)`.
- `Watcher` keeps `watch`, `notice`, `directory_event`, `flush`, `run`, `stop`, `unwatched`, and gains `overflow()`.

- [ ] **Step 1: Add the dependency**

Run: `uv add --project helper 'inotify_simple>=1.3.5'`
Then remove watchdog: `uv remove --project helper watchdog`
Expected: `helper/pyproject.toml` lists `inotify_simple`, not `watchdog`; `helper/uv.lock` updated.

- [ ] **Step 2: Write the failing observer tests** in `tests/helper/test_inotify.py`

```python
import os
import threading
import time
from pathlib import Path

from omafindd.inotify import Event, InotifyObserver


def _inotify_fds():
    count = 0
    for name in os.listdir("/proc/self/fd"):
        try:
            if os.readlink(f"/proc/self/fd/{name}") == "anon_inode:inotify":
                count += 1
        except OSError:
            pass
    return count


class Recorder:
    def __init__(self):
        self.events = []
        self.seen = threading.Event()

    def on_any_event(self, event):
        self.events.append(event)
        self.seen.set()


def test_two_hundred_directories_share_one_instance_and_thread(tmp_path):
    folders = [tmp_path / f"d{n}" for n in range(200)]
    for folder in folders:
        folder.mkdir()
    fds, threads = _inotify_fds(), threading.active_count()
    observer = InotifyObserver()
    observer.start()
    try:
        for folder in folders:
            observer.schedule(Recorder(), str(folder))
        assert _inotify_fds() == fds + 1
        assert threading.active_count() == threads + 1
    finally:
        observer.stop()
        observer.join()
    assert _inotify_fds() == fds


def test_file_write_reaches_the_directory_handler(tmp_path):
    observer, recorder = InotifyObserver(), Recorder()
    observer.start()
    try:
        observer.schedule(recorder, str(tmp_path))
        (tmp_path / "note.txt").write_text("x")
        assert recorder.seen.wait(5)
        assert Event("created", str(tmp_path / "note.txt"), False) in recorder.events
    finally:
        observer.stop()
        observer.join()


def test_overflow_calls_on_overflow():
    observer = InotifyObserver()
    called = []
    observer.on_overflow = lambda: called.append(True)
    observer._dispatch(type("E", (), {"wd": -1, "mask": 0x4000, "cookie": 0, "name": ""})())
    assert called == [True]


def test_stale_watch_does_not_remove_reused_descriptor(tmp_path):
    observer = InotifyObserver()
    observer.start()
    try:
        first = tmp_path / "a"
        first.mkdir()
        old = observer.schedule(Recorder(), str(first))
        first.rmdir()
        deadline = time.monotonic() + 5
        while old.wd in observer._watches and time.monotonic() < deadline:
            time.sleep(0.01)
        second = tmp_path / "b"
        second.mkdir()
        new = observer.schedule(Recorder(), str(second))
        observer.unschedule(old)
        assert observer._watches[new.wd][1] == str(second)
    finally:
        observer.stop()
        observer.join()
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run --project helper pytest tests/helper/test_inotify.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'omafindd.inotify'`.

- [ ] **Step 4: Write `helper/omafindd/inotify.py`**

```python
"""One inotify instance for every watched directory, read by one thread."""

import errno
import os
import threading
from dataclasses import dataclass

from inotify_simple import INotify, flags

MASK = (flags.CREATE | flags.DELETE | flags.MODIFY | flags.MOVED_FROM | flags.MOVED_TO
        | flags.CLOSE_WRITE | flags.ONLYDIR)


@dataclass(frozen=True)
class Event:
    event_type: str
    src_path: str
    is_directory: bool
    dest_path: str = ""


@dataclass(frozen=True)
class Watch:
    wd: int
    path: str


def _event_type(mask):
    if mask & (flags.CREATE | flags.MOVED_TO):
        return "created"
    if mask & (flags.DELETE | flags.MOVED_FROM):
        return "deleted"
    if mask & flags.CLOSE_WRITE:
        return "closed"
    if mask & flags.MODIFY:
        return "modified"
    return None


class InotifyObserver:
    """The subset of watchdog's Observer that Watcher uses, on a single inotify fd."""

    def __init__(self, *, inotify_factory=INotify):
        self._factory = inotify_factory
        self._inotify = None
        self._watches = {}
        self._lock = threading.Lock()
        self._thread = None
        self._stopped = threading.Event()
        self.on_overflow = lambda: None

    def _ensure(self):
        if self._inotify is None:
            self._inotify = self._factory()
        return self._inotify

    def start(self):
        self._ensure()
        self._stopped.clear()
        self._thread = threading.Thread(target=self._run, name="omafind-inotify", daemon=True)
        self._thread.start()

    def schedule(self, handler, path, *, recursive=False):
        wd = self._ensure().add_watch(path, MASK)
        with self._lock:
            self._watches[wd] = (handler, path)
        return Watch(wd, path)

    def unschedule(self, watch):
        with self._lock:
            entry = self._watches.get(watch.wd)
            # inotify reuses a descriptor after IN_IGNORED; only drop the directory we added.
            if entry is None or entry[1] != watch.path:
                return
            del self._watches[watch.wd]
        try:
            self._inotify.rm_watch(watch.wd)
        except OSError as error:
            if error.errno != errno.EINVAL:
                raise

    def unschedule_all(self):
        with self._lock:
            watches = [Watch(wd, path) for wd, (_, path) in self._watches.items()]
        for watch in watches:
            self.unschedule(watch)

    def stop(self):
        self._stopped.set()

    def join(self):
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        if self._inotify is not None:
            self._inotify.close()
            self._inotify = None
        with self._lock:
            self._watches.clear()

    def _run(self):
        while not self._stopped.is_set():
            try:
                events = self._inotify.read(timeout=250)
            except OSError:
                if self._stopped.is_set():
                    return
                raise
            for event in events:
                self._dispatch(event)

    def _dispatch(self, event):
        if event.mask & flags.Q_OVERFLOW:
            self.on_overflow()
            return
        with self._lock:
            if event.mask & flags.IGNORED:
                self._watches.pop(event.wd, None)
                return
            entry = self._watches.get(event.wd)
        kind = _event_type(event.mask)
        if entry is None or kind is None or not event.name:
            return
        handler, directory = entry
        handler.on_any_event(Event(kind, os.path.join(directory, event.name),
                                   bool(event.mask & flags.ISDIR)))
```

- [ ] **Step 5: Run the observer tests**

Run: `uv run --project helper pytest tests/helper/test_inotify.py -q`
Expected: 4 passed.

- [ ] **Step 6: Write the failing watcher tests** (append to `tests/helper/test_watcher.py`; replace the `watchdog.events` import in `test_created_subdirectory_gets_watch_and_deleted_watches_are_removed` with `from omafindd.inotify import Event` and build events as `Event('created', str(root / 'new'), True)` / `Event('deleted', str(root / 'new'), True)`)

```python
async def test_overflow_marks_every_root_dirty(tree):
    from omafindd.watcher import Watcher

    root, _ = tree
    calls = []

    async def dirty(setting, dirs):
        calls.append((setting['path'], dirs))

    watcher = Watcher(on_dirty=dirty, observer_factory=Observer)
    watcher.watch([{'path': str(root)}])
    try:
        watcher.overflow()
        await asyncio.sleep(0)
        await watcher.flush()
        assert calls == [(str(root), None)]
    finally:
        watcher.stop()


async def test_enospc_logs_one_line_for_many_directories(tree, caplog):
    import errno

    from omafindd.watcher import Watcher

    root, _ = tree
    for n in range(5):
        (root / f'full{n}').mkdir()

    class Full(Observer):
        def schedule(self, handler, path, *, recursive):
            if path != str(root):
                raise OSError(errno.ENOSPC, 'no space', path)
            return super().schedule(handler, path, recursive=recursive)

    watcher = Watcher(on_dirty=None, observer_factory=Full)
    try:
        watcher.watch([{'path': str(root)}])
        assert watcher.unwatched == 5
        assert caplog.text.count('Watcher') == 1
    finally:
        watcher.stop()


async def test_renamed_directory_moves_its_watches(tree, monkeypatch):
    from omafindd.inotify import Event

    root, store = tree

    async def inline(callback, *args):
        return callback(*args)

    monkeypatch.setattr(asyncio, 'to_thread', inline)
    (root / 'old/nested').mkdir(parents=True)
    watcher, _, _ = await watcher_for(root, store)
    try:
        handler = watcher.observer.watches[0][0]
        (root / 'old').rename(root / 'new')
        handler.on_any_event(Event('deleted', str(root / 'old'), True))
        handler.on_any_event(Event('created', str(root / 'new'), True))
        await asyncio.sleep(0)
        await watcher.flush()
        assert {item[1] for item in watcher.observer.watches} == {
            str(root), str(root / 'new'), str(root / 'new/nested')}
    finally:
        watcher.stop()
```

`watcher_for` asserts `observer.watches[0][1:] == (str(root), False)`; it stays valid because the fake `Observer` is unchanged.

- [ ] **Step 7: Run them to verify they fail**

Run: `uv run --project helper pytest tests/helper/test_watcher.py -q`
Expected: FAIL: `AttributeError: 'Watcher' object has no attribute 'overflow'` and the ENOSPC count is 5, not 1.

- [ ] **Step 8: Change `helper/omafindd/watcher.py`**

Replace the watchdog imports and `_Handler` base:

```python
from . import rules
from .inotify import InotifyObserver

logger = logging.getLogger(__name__)


class _Handler:
    def __init__(self, watcher):
        self.watcher = watcher
```

(`on_any_event` body unchanged.) Change the constructor default and wire overflow:

```python
    def __init__(self, *, on_dirty, clock=time.monotonic, sleep=asyncio.sleep,
                 observer_factory=InotifyObserver, window=2.0):
        ...existing lines...
        self._directory_events = []
        self._overflow = False
        if hasattr(self.observer, 'on_overflow'):
            self.observer.on_overflow = self.overflow
```

Replace `_add_tree`'s error reporting so a pass logs once:

```python
    def _add_tree(self, path):
        roots = [root for root in self.roots if path.is_relative_to(root)]
        if path.is_symlink() or not roots or not any(self._allowed(path, root) for root in roots):
            return
        failures = []

        def failed(error):
            self.unwatched += 1
            failures.append(error.errno)

        for folder, dirs, _ in os.walk(path, onerror=failed):
            ...unchanged body...
        if failures:
            logger.warning('Watcher could not watch %d directories (errno=%s)',
                           len(failures), failures[0])
```

Add overflow handling:

```python
    def overflow(self) -> None:
        if self.loop is not None and not self.stopped:
            self.loop.call_soon_threadsafe(setattr, self, '_overflow', True)
```

and at the top of `flush`, before the directory events:

```python
        if self._overflow:
            self._overflow = False
            with self._lock:
                settings = list(self.roots.values())
            for setting in settings:
                await self.on_dirty(setting, None)
```

`main.on_dirty` already turns `dirs=None` into a whole-volume reconcile through `defer(uuid, None)`.

- [ ] **Step 9: Update the missing-dependency test** in `tests/helper/test_update.py`: replace both `watchdog` strings with `inotify_simple`.

- [ ] **Step 10: Run the watcher, inotify and update tests**

Run: `uv run --project helper pytest tests/helper/test_watcher.py tests/helper/test_inotify.py tests/helper/test_update.py tests/helper/test_main_freshness.py -q`
Expected: all pass. `grep -rn watchdog helper tests` prints nothing.

- [ ] **Step 11: Commit**

```bash
git add helper/omafindd/inotify.py helper/omafindd/watcher.py helper/pyproject.toml helper/uv.lock tests/helper/test_inotify.py tests/helper/test_watcher.py tests/helper/test_update.py
git commit -S -m "fix(omafindd): watch every folder through one inotify instance"
```

---

### Task 2: Token-safe chunks and chunked PDF pages

**Files:**
- Modify: `helper/omafindd/extractors.py:54-85` (`chunks`), `helper/omafindd/extractors.py:166-170` (PDF text pages)
- Test: `tests/helper/test_chunker.py`, `tests/helper/test_extract_pdf.py`

**Interfaces:**
- Produces: `extractors.TOKEN_CAP = 1800`, `extractors.estimated_tokens(text: str) -> int`. `chunks(text)` unchanged signature; every segment satisfies `estimated_tokens(segment.text) <= TOKEN_CAP`. PDF text pages produce `Segment("page", "text", chunk, loc=page, loc_end=page)`, one or more per page.

- [ ] **Step 1: Write the failing tests**

`tests/helper/test_chunker.py`:

```python
def test_dense_text_splits_below_token_cap():
    from omafindd.extractors import TOKEN_CAP, chunks, estimated_tokens

    text = "∑∫√≈ 数学 " * 400
    segments = chunks(text)
    assert len(segments) > 1
    assert all(estimated_tokens(segment.text) <= TOKEN_CAP for segment in segments)


def test_ascii_text_estimate_is_one_token_per_character():
    from omafindd.extractors import estimated_tokens

    assert estimated_tokens("abcd") == 4
    assert estimated_tokens("数") == 3
```

`tests/helper/test_extract_pdf.py` (uses the same fixture helpers as `test_pdf_text_page`; read that test first and mirror how it builds a PDF from `support.corpus.pdf`):

```python
def test_long_pdf_page_becomes_several_segments_on_one_page(tmp_path):
    from omafindd.extractors import TOKEN_CAP, estimated_tokens, extract
    from support.corpus import pdf

    path = tmp_path / "long.pdf"
    pdf(path, ["word " * 1500])
    result = extract(path, "pdf", 1)
    pages = [segment for segment in result.segments if segment.kind == "page"]
    assert len(pages) >= 3
    assert {(segment.loc, segment.loc_end) for segment in pages} == {(1, 1)}
    assert all(estimated_tokens(segment.text) <= TOKEN_CAP for segment in pages)
```

If `support.corpus.pdf` takes a different argument shape, adapt the call to it; the assertions stay.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --project helper pytest tests/helper/test_chunker.py tests/helper/test_extract_pdf.py -q`
Expected: FAIL with `ImportError: cannot import name 'TOKEN_CAP'`.

- [ ] **Step 3: Implement**

In `extractors.py` above `chunks`:

```python
# embeddinggemma reads at most 2,048 tokens per input, prefix included. Plain ASCII is never
# more than one token per character; other characters can take up to three.
TOKEN_CAP = 1800


def estimated_tokens(text: str) -> int:
    return sum(1 if ord(character) < 128 else 3 for character in text)
```

In `chunks`, right after `end` is chosen at the whitespace boundary and before `left, right = start, end`:

```python
        while end - start > 1 and estimated_tokens(text[start:end]) > TOKEN_CAP:
            end = start + (end - start) * 3 // 4
```

Replace the PDF text-page branch:

```python
            if len(body) >= 200:
                for piece in chunks(body):
                    segments.append(Segment("page", "text", piece.text, loc=page, loc_end=page))
                continue
```

- [ ] **Step 4: Run the extractor, chunker, job and search tests**

Run: `uv run --project helper pytest tests/helper/test_chunker.py tests/helper/test_extract_pdf.py tests/helper/test_jobs.py tests/helper/test_search.py tests/helper/test_preview.py -q`
Expected: all pass. If a search or preview test assumed one segment per PDF page, update its expectation to group by `loc`, not to undo the split.

- [ ] **Step 5: Commit**

```bash
git add helper/omafindd/extractors.py tests/helper/test_chunker.py tests/helper/test_extract_pdf.py
git commit -S -m "fix(omafindd): split pdf pages and dense text under the token cap"
```

---

### Task 3: A rejected embedding fails one file, not the run

**Files:**
- Modify: `helper/omafindd/embedder.py:265-281`, `helper/omafindd/jobs.py:142-235`, `helper/omafindd/store.py` (add `halt`)
- Test: `tests/helper/test_jobs.py`, `tests/helper/test_embedder.py`

**Interfaces:**
- Produces: `embedder.EmbeddingRejected(EmbeddingError)` raised for an HTTP error status, message `"HTTP <status>: <server message>"` (server message cut to 200 characters). `Store.halt(file: int, detail: str)` sets `detail` on a `partial` file and keeps its segments.

- [ ] **Step 1: Write the failing tests** in `tests/helper/test_jobs.py`

```python
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
    assert store.db.execute("SELECT count(*) FROM segments").fetchone()[0] == 30
```

Keep `test_nonprecision_embedding_error_still_propagates` as it is: a plain `EmbeddingError` (server gone) still ends the run.

In `tests/helper/test_embedder.py`, add (mirror the existing `httpx.MockTransport` pattern in that file; read it first):

```python
async def test_http_error_raises_rejected_with_server_message():
    import httpx
    from omafindd.embedder import Embedder, EmbeddingRejected, Text

    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200)
        return httpx.Response(500, json={"error": {"message": "input (3359 tokens) is too large"}})

    embedder = Embedder(base_url="http://test", api_key="k")
    await embedder.start("full")
    embedder._client._transport = httpx.MockTransport(handler)
    with pytest.raises(EmbeddingRejected, match="HTTP 500: input \\(3359 tokens\\) is too large"):
        await embedder.embed([Text("x")])
```

If `start("full")` with a shared URL performs `/health` before the transport swap, construct the client with the mock transport the way the existing tests do instead; the assertion stays.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --project helper pytest tests/helper/test_jobs.py tests/helper/test_embedder.py -q`
Expected: FAIL with `ImportError: cannot import name 'EmbeddingRejected'`.

- [ ] **Step 3: Implement**

`embedder.py`, next to `EmbeddingError`:

```python
class EmbeddingRejected(EmbeddingError):
    """The server answered with an error status; the input, not the server, is at fault."""
```

In `embed`, split the request error handling:

```python
                try:
                    response = await client.post("/v1/embeddings", json=build_request(batch))
                    response.raise_for_status()
                except httpx.HTTPStatusError as error:
                    try:
                        message = str(error.response.json()["error"]["message"])
                    except (ValueError, KeyError, TypeError):
                        message = error.response.reason_phrase
                    raise EmbeddingRejected(
                        f"HTTP {error.response.status_code}: {message[:200]}") from error
                except (httpx.HTTPError, RuntimeError) as error:
                    raise EmbeddingError("Embedding request failed") from error
```

`store.py`, after `fail`:

```python
    def halt(self, file: int, detail: str):
        """Stops a partial file where it is: its segments stay and it leaves the queue."""
        with self.db:
            self.db.execute("UPDATE files SET detail=? WHERE id=? AND state='partial'",
                            (detail, file))
```

`jobs.py`: import `EmbeddingRejected` and `logging` (`logger = logging.getLogger(__name__)`), and add a handler before `except EmbeddingError as error:`:

```python
                    except EmbeddingRejected as error:
                        logger.warning("Embedding rejected file %s (%s)", file, error)
                        if append:
                            self.store.halt(file, "embedding-failed")
                        else:
                            self.store.fail(file, "embedding-failed")
```

The video soundtrack branch (`except (ValueError, EmbeddingError)` inside the group loop) already catches `EmbeddingRejected` as an `EmbeddingError`; leave it.

- [ ] **Step 4: Run the tests**

Run: `uv run --project helper pytest tests/helper/test_jobs.py tests/helper/test_embedder.py tests/helper/test_store.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add helper/omafindd/embedder.py helper/omafindd/jobs.py helper/omafindd/store.py tests/helper/test_jobs.py tests/helper/test_embedder.py
git commit -S -m "fix(omafindd): fail only the file the embedding server rejects"
```

---

### Task 4: A warm server never answers "starting"

**Files:**
- Modify: `helper/omafindd/embedder.py` (`Embedder.ready`, `embed` lock), `helper/omafindd/embedding.py` (`Adapter.ready`), `helper/omafindd/main.py:46-71` (`_LazyEmbedder.ready`), `helper/omafindd/service.py:215-226`, `tests/fakes/embedder.py`
- Test: `tests/helper/test_embedder.py`, `tests/helper/test_ipc_search.py`

**Interfaces:**
- Produces: `Embedder.ready(mode) -> bool` and `Adapter.ready(mode) -> bool`, lock-free. `Embedder.embed` holds `self._requests` (an `asyncio.Semaphore(2)`) instead of `self._lock`.

- [ ] **Step 1: Write the failing tests**

In `tests/helper/test_ipc_search.py` (it already has `store`, `seeded_search`, `FakeEmbedder`, `Settings` and `State`):

```python
async def test_warm_server_answers_while_start_lock_is_held(store, tmp_path):
    from omafindd.service import SearchService

    await seeded_search(store, tmp_path)
    gate = asyncio.Event()

    class Busy(FakeEmbedder):
        async def start(self, mode):
            await gate.wait()

    embedder = Busy()
    embedder.mode = 'full'
    service = SearchService(
        store.path.parent, lambda: Settings(), embedder, State(model='ready'),
        volume_resolver=lambda path, **kwargs: ('v', tmp_path), mounts_resolver=lambda: {}
    )
    try:
        reply = await service.handle({'t': 'search', 'seq': 1, 'q': 'lunar'})
        assert reply['degraded'] is None and 'meaning' in reply['legs']
    finally:
        gate.set()
        await service.stop()
```

In `tests/helper/test_embedder.py`:

```python
async def test_ready_reads_mode_without_the_lock():
    from omafindd.embedder import Embedder

    embedder = Embedder(base_url="http://test", api_key="k")
    assert not embedder.ready("text")
    embedder.mode, embedder._client = "full", object()
    async with embedder._lock:
        assert embedder.ready("text") and embedder.ready("full")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --project helper pytest tests/helper/test_embedder.py tests/helper/test_ipc_search.py -q`
Expected: FAIL: `AttributeError: 'Embedder' object has no attribute 'ready'`, and the service reply has `degraded: 'the embedding server is starting'`.

- [ ] **Step 3: Implement**

`embedder.py`, in `Embedder.__init__`: `self._requests = asyncio.Semaphore(2)`. Add:

```python
    def ready(self, mode: Mode) -> bool:
        if self._client is None or not (self.mode == mode or self.mode == "full"):
            return False
        return self.shared or self._process is not None and self._process.returncode is None
```

In `embed`, replace `async with self._lock:` with `async with self._requests:`. The snapshot of `process, client` at the top already protects against a concurrent `stop()`; a request on a closed client raises `RuntimeError`, which becomes `EmbeddingError`.

`embedding.py`, in `Adapter`:

```python
    def ready(self, mode) -> bool:
        return self.runtime.ready(mode)
```

`service.py`, in `_start_query`, after the finished-warm-task check:

```python
        if self.embedder.ready(mode):
            return
```

Give `FakeEmbedder` (`tests/fakes/embedder.py`) a `ready(self, mode)` returning `self.mode in (mode, "full")`, and `main._LazyEmbedder` (`helper/omafindd/main.py:46`) a `ready(self, mode)` returning `self.instance is not None and self.instance.ready(mode)`, since the daemon's `SearchService` holds the lazy wrapper.

- [ ] **Step 4: Run the tests**

Run: `uv run --project helper pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add helper/omafindd/embedder.py helper/omafindd/embedding.py helper/omafindd/main.py helper/omafindd/service.py tests/fakes/embedder.py tests/helper/test_embedder.py tests/helper/test_ipc_search.py
git commit -S -m "fix(omafindd): answer queries at once while the server is warm"
```

---

### Task 5: The meaning leg always fires

**Files:**
- Modify: `lib/searchState.js`, `SearchView.qml:105-120, 377-387, 444-450`
- Test: `tests/js/searchState.test.mjs`, `tests/js/searchView.test.mjs`

**Interfaces:**
- Produces: `SearchState.remaining(state, type, now) -> number` (milliseconds left before the leg is due, `0` when due, sent or idle). `SearchView.arm(timer, delay)`.

- [ ] **Step 1: Write the failing tests**

`tests/js/searchState.test.mjs`:

```javascript
test('an early meaning tick reports the time left and a later tick sends once', () => {
  const { initial, reduce, remaining } = search();
  let state = reduce(initial(), { type: 'typed', query: 'router', now: 1000 }).state;
  state = reduce(state, { type: 'words-due', now: 1050 }).state;
  const early = reduce(state, { type: 'meaning-due', now: 1199 });
  assert.equal(early.send, null);
  assert.equal(remaining(state, 'meaning-due', 1199), 1);
  const late = reduce(early.state, { type: 'meaning-due', now: 1200 });
  assert.deepEqual(plain(late.send.legs), ['words', 'meaning']);
  assert.equal(remaining(late.state, 'meaning-due', 1300), 0);
  assert.equal(reduce(late.state, { type: 'meaning-due', now: 1300 }).send, null);
});
```

`tests/js/searchView.test.mjs`:

```javascript
test('an early timer tick re-arms the timer for the remaining time', () => {
  const armed = [];
  const timer = { interval: 200, restart() { armed.push(this.interval); } };
  const context = view({
    SearchState: load('format.js', 'results.js', 'searchState.js'),
    service: { send() { return true; } },
    meaningTimer: timer, wordsTimer: { interval: 50, restart() {} },
    Date: { now: () => 1150 },
    search: { query: 'router', seq: 1, phase: 'words', sentWords: 1, sentMeaning: 0,
      reply: null, started: 1000 },
  });
  context.due('meaning-due');
  assert.deepEqual(armed, [50]);
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `node --test tests/js/searchState.test.mjs tests/js/searchView.test.mjs`
Expected: FAIL: `remaining is not a function`; `armed` is `[]`.

- [ ] **Step 3: Implement**

`lib/searchState.js`, after `reduce`:

```javascript
// QML timers run on the frame clock and can fire a frame before Date.now() says the delay is
// over. The caller re-arms its timer for what is left.
function remaining(state, type, now) {
  if (!parse(state.query).text.trim()) return 0
  var meaning = type === "meaning-due"
  var unsent = meaning ? state.sentMeaning !== state.seq
    : state.sentWords !== state.seq && state.sentMeaning !== state.seq
  if (!unsent) return 0
  return Math.max(0, state.started + (meaning ? meaningDelay : wordsDelay) - now)
}
```

`SearchView.qml`: add

```qml
  function arm(timer, delay) {
    timer.interval = delay
    timer.restart()
  }
```

change `due`:

```qml
  function due(type) {
    var now = Date.now()
    var next = SearchState.reduce(search, {type: type, now: now})
    if (next.send && (!service || !service.send(next.send))) {
      next.state.sentWords = search.sentWords
      next.state.sentMeaning = search.sentMeaning
    }
    var left = next.send ? 0 : SearchState.remaining(search, type, now)
    search = next.state
    if (left > 0) arm(type === "meaning-due" ? meaningTimer : wordsTimer, left)
  }
```

and replace the three plain restarts (`wordsTimer.restart()`, `meaningTimer.restart()` at the end of the typed handler, and `meaningTimer.restart()` in the refresh branch) with `arm(wordsTimer, SearchState.wordsDelay)` and `arm(meaningTimer, SearchState.meaningDelay)`.

- [ ] **Step 4: Run the JS tests and qmllint**

Run: `node --test "tests/js/*.test.mjs" && scripts/qmllint.sh`
Expected: all pass, exit 0.

- [ ] **Step 5: Commit**

```bash
git add lib/searchState.js SearchView.qml tests/js/searchState.test.mjs tests/js/searchView.test.mjs
git commit -S -m "fix(overlay): re-arm the meaning timer when it fires early"
```

---

### Task 6: `code:` explains an empty code index

**Files:**
- Modify: `helper/omafindd/search_code.py:160-162`, `lib/results.js:110-117`
- Test: `tests/helper/test_code.py` (or wherever `search_code` is tested: `grep -rn "search_code(" tests/helper`), `tests/js/results.test.mjs`

**Interfaces:**
- Produces: code replies carry `"notice": "no-code-index"` when there are no code roots or no `code.sqlite`; otherwise no `notice` key.

- [ ] **Step 1: Write the failing tests**

Python:

```python
async def test_code_search_without_an_index_says_so(tmp_path):
    from omafindd.search_code import search_code

    reply = await search_code(None, "parse arguments", roots=[], directory=tmp_path,
                              legs=["words", "meaning"], limit=10, seq=4, begun=0.0)
    assert reply["notice"] == "no-code-index" and reply["degraded"] is None
    assert reply["items"] == []
```

JS (`tests/js/results.test.mjs`; load the module the way the file already does):

```javascript
test('a code search with no code index explains the empty result', () => {
  const R = results();
  assert.equal(R.footerLeft({ phase: 'done', prefix: 'code:',
    reply: { total: 0, items: [], notice: 'no-code-index' } }),
    'No code is indexed yet. Turn on Code for a repository in setup.');
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --project helper pytest tests/helper -q -k code_search_without && node --test tests/js/results.test.mjs`
Expected: FAIL: `KeyError: 'notice'`; the footer reads `0 results in your code`.

- [ ] **Step 3: Implement**

`search_code.py`, after the `reply = {...}` line:

```python
    if not available:
        reply["notice"] = "no-code-index"
```

`lib/results.js`, first line inside `footerLeft` after the words check:

```javascript
  if ((view.reply || {}).notice === "no-code-index")
    return "No code is indexed yet. Turn on Code for a repository in setup."
```

- [ ] **Step 4: Run the tests**

Run: `uv run --project helper pytest -q && node --test "tests/js/*.test.mjs"`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add helper/omafindd/search_code.py lib/results.js tests/helper tests/js/results.test.mjs
git commit -S -m "fix(overlay): explain why a code search has no results"
```

(Stage the exact python test file you edited instead of `tests/helper`.)

---

### Task 7: Discovery tells repos from worktrees and reports both

**Files:**
- Modify: `helper/omafindd/discovery.py:79-91, 117-122, 135-145, 178-190, 195-253, 256-268`
- Test: `tests/helper/test_discovery.py`

**Interfaces:**
- Produces: `discovery.git_kind(path: str) -> "repo" | "worktree" | None`. Rows from `folders()` carry `repo: bool` and `worktree: bool`. `Walk.repos: list[str]`, `Walk.worktrees: list[str]`; the final batch and a done `snapshot()` carry `"repos": [...]` and `"worktrees": [...]` (sorted absolute paths).

- [ ] **Step 1: Write the failing tests**

```python
def _repo(path):
    (path / ".git").mkdir(parents=True)


def _linked(path, gitdir, *, worktree):
    path.mkdir(parents=True)
    gitdir.mkdir(parents=True)
    if worktree:
        (gitdir / "commondir").write_text("../..\n")
    (path / ".git").write_text(f"gitdir: {gitdir}\n")


def test_git_kind_tells_repo_worktree_submodule_and_plain(tmp_path):
    _repo(tmp_path / "main")
    _linked(tmp_path / "wt", tmp_path / "main/.git/worktrees/wt", worktree=True)
    _linked(tmp_path / "main/sub", tmp_path / "main/.git/modules/sub", worktree=False)
    (tmp_path / "plain").mkdir()
    (tmp_path / "odd").mkdir()
    (tmp_path / "odd/.git").write_text("not a gitdir line")
    assert [discovery.git_kind(str(tmp_path / name)) for name in
            ("main", "wt", "main/sub", "plain", "odd")] == [
        "repo", "worktree", "repo", None, None]


def test_relative_gitdir_resolves_against_the_folder(tmp_path):
    _repo(tmp_path / "main")
    (tmp_path / "main/.git/worktrees/wt").mkdir(parents=True)
    (tmp_path / "main/.git/worktrees/wt/commondir").write_text("../..\n")
    (tmp_path / "wt").mkdir()
    (tmp_path / "wt/.git").write_text("gitdir: ../main/.git/worktrees/wt\n")
    assert discovery.git_kind(str(tmp_path / "wt")) == "worktree"


def test_rows_and_walk_report_repos_and_worktrees(tmp_path):
    _repo(tmp_path / "proj/main")
    (tmp_path / "proj/main/a.md").write_text("a")
    _linked(tmp_path / "proj/wt", tmp_path / "proj/main/.git/worktrees/wt", worktree=True)
    (tmp_path / "proj/wt/b.md").write_text("b")
    (tmp_path / "proj/code-only").mkdir()
    (tmp_path / "proj/code-only/.git").mkdir()
    (tmp_path / "proj/code-only/x.py").write_text("x")
    rows = {row["name"]: row for row in discovery.folders(tmp_path / "proj")}
    assert (rows["main"]["repo"], rows["main"]["worktree"]) == (True, False)
    assert (rows["wt"]["repo"], rows["wt"]["worktree"]) == (False, True)
    walk = discovery.Walk(tmp_path)
    batches = []
    walk.run(batches.append)
    assert batches[-1]["repos"] == [str(tmp_path / "proj/code-only"), str(tmp_path / "proj/main")]
    assert batches[-1]["worktrees"] == [str(tmp_path / "proj/wt")]
    assert walk.snapshot()["worktrees"] == [str(tmp_path / "proj/wt")]
```

`test_walk_rolls_counts_up_in_batches` asserts `final["datasets"] == []`; also assert `final["repos"] == [] and final["worktrees"] == []` there.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --project helper pytest tests/helper/test_discovery.py -q`
Expected: FAIL: `AttributeError: module 'omafindd.discovery' has no attribute 'git_kind'`.

- [ ] **Step 3: Implement**

Add near the top of `discovery.py`:

```python
def git_kind(path: str) -> str | None:
    """`repo` for a `.git` directory or a submodule, `worktree` for a linked worktree."""
    marker = os.path.join(path, ".git")
    if os.path.isdir(marker):
        return "repo"
    try:
        with open(marker, encoding="utf-8") as stream:
            line = stream.readline(4096)
    except (OSError, UnicodeDecodeError):
        return None
    if not line.startswith("gitdir:"):
        return None
    gitdir = os.path.join(path, line[len("gitdir:"):].strip())
    # Only a linked worktree's gitdir has `commondir`; a submodule's does not.
    return "worktree" if os.path.isfile(os.path.join(gitdir, "commondir")) else "repo"
```

In `folders()` build rows with:

```python
    rows = []
    for name in names:
        kind = git_kind(name)
        rows.append({"path": name, "name": os.path.basename(name), "repo": kind == "repo",
                     "worktree": kind == "worktree", "hasChildren": _has_children(name)})
    return rows
```

and in `top()`'s volume rows replace `"repo": os.path.exists(...)` with `"repo": git_kind(str(mount)) == "repo", "worktree": git_kind(str(mount)) == "worktree"`.

In `Walk.__init__`: `self.repos, self.worktrees, self._checked = [], [], set()`. Add:

```python
    def _note_git(self, folder, root):
        while folder not in self._checked and len(folder) >= len(root):
            self._checked.add(folder)
            kind = git_kind(folder)
            if kind == "repo":
                self.repos.append(folder)
            elif kind == "worktree":
                self.worktrees.append(folder)
            folder = os.path.dirname(folder)
```

In `run()`, call `self._note_git(os.path.dirname(name), root)` right after the UTF-8 check and before `classify_name`, so folders holding only code files are seen. At the end, inside the `with self._lock:` that sets `self.datasets`, add `self.repos.sort()` and `self.worktrees.sort()`, and set `batch["repos"] = list(self.repos)` and `batch["worktrees"] = list(self.worktrees)` next to `batch["datasets"]`. In `snapshot()`, inside `if self.done:`, add the same two keys.

- [ ] **Step 4: Run the tests**

Run: `uv run --project helper pytest tests/helper/test_discovery.py tests/helper/test_ipc_setup.py -q`
Expected: all pass. Fix any IPC test that compares a whole `discover_counts` body by adding the two keys to its expectation.

- [ ] **Step 5: Commit**

```bash
git add helper/omafindd/discovery.py tests/helper/test_discovery.py tests/helper/test_ipc_setup.py
git commit -S -m "feat(setup): detect git worktrees and report repos from the walk"
```

---

### Task 8: Folders step: sort by size, skip worktrees, code on for repos, tag colours

**Files:**
- Modify: `lib/tree.js`, `Service.qml:43, 385-402, 449-476`, `ui/FolderTree.qml:95-110, 132-150, 185-212`, `ui/SetupFolders.qml:16, 40-60, 88-95`, `ui/DriveDialog.qml:78-86, 126`, `ui/RuleTag.qml`, `docs/DESIGN.md` (tag colour line near line 96)
- Test: `tests/js/tree.test.mjs`, `tests/js/setupFolders.test.mjs`, `tests/js/serviceDiscovery.test.mjs`

**Interfaces:**
- Consumes: `discover_counts.repos`, `.worktrees`; row fields `repo`, `worktree` (Task 7).
- Produces: `Tree.byCount(rows, countOf) -> rows` (new array), `Tree.addCode(state, repos, proposed, blocked) -> state`. `Service.repos` and `Service.worktrees`: objects keyed by path, values `{path}`. `SetupFolders.offerRepos()`, `SetupFolders.proposedCode`.

- [ ] **Step 1: Write the failing JS tests**

`tests/js/tree.test.mjs`:

```javascript
test('rows sort by known total, then unknown, then zero, then name', () => {
  const Tree = load('tree.js');
  const counts = { '/h/a': { text: 1, pdf: 0, image: 0, video: 0, audio: 0 },
    '/h/b': { text: 0, pdf: 0, image: 9, video: 0, audio: 0 },
    '/h/z': { text: 0, pdf: 0, image: 0, video: 0, audio: 0 } };
  const rows = ['/h/z', '/h/Unknown', '/h/a', '/h/b', '/h/c'].map(path => (
    { path, name: path.slice(3) }));
  const sorted = Tree.byCount(rows, path => counts[path] || null);
  assert.deepEqual(sorted.map(row => row.path), ['/h/b', '/h/a', '/h/c', '/h/Unknown', '/h/z']);
});

test('repos under a searched folder get code once; inside skipped folders or worktrees they do not', () => {
  const Tree = load('tree.js');
  const state = { chosen: ['/h/p'], skipped: ['/h/p/skip'], code: [] };
  const repos = [{ path: '/h/p/a' }, { path: '/h/p/skip/b' }, { path: '/h/p/wt/c' },
    { path: '/h/other/d' }];
  const next = Tree.addCode(state, repos, [], ['/h/p/wt']);
  assert.deepEqual(plain(next.code), ['/h/p/a']);
  assert.deepEqual(plain(Tree.addCode(Tree.toggleCode(next, '/h/p/a'), repos, ['/h/p/a'], []).code), []);
});
```

Name the second test exactly `repos inside skipped folders or worktrees are not offered code` (Review Focus 3).

`tests/js/setupFolders.test.mjs` (extend the `folders()` helper's `service` with `worktrees: {}` and `repos: {}` defaults, and pass `proposedCode: []`):

```javascript
test('worktrees under a searched folder start unchecked and repos start with code', () => {
  const ctx = folders({
    choices: { chosen: ['/h/p'], skipped: [], code: [] },
    service: { datasets: {}, worktrees: { '/h/p/wt': { path: '/h/p/wt' } },
      repos: { '/h/p/main': { path: '/h/p/main' } } },
  });
  ctx.offerDatasets();
  ctx.offerRepos();
  assert.deepEqual(plain(ctx.choices.skipped), ['/h/p/wt']);
  assert.deepEqual(plain(ctx.choices.code), ['/h/p/main']);
});
```

`tests/js/serviceDiscovery.test.mjs`: follow its pattern for `receiveCounts` and add:

```javascript
test('the final walk batch records repos and worktrees and a reset clears them', () => {
  const service = makeService();  // the file's existing builder
  service.receiveCounts({ root: '/h', counts: {}, done: true, datasets: [],
    repos: ['/h/p/main'], worktrees: ['/h/p/wt'] });
  assert.deepEqual(Object.keys(service.repos), ['/h/p/main']);
  assert.deepEqual(Object.keys(service.worktrees), ['/h/p/wt']);
  service.receiveCounts({ root: '/h', counts: {}, reset: true });
  assert.deepEqual(Object.keys(service.repos), []);
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `node --test tests/js/tree.test.mjs tests/js/setupFolders.test.mjs tests/js/serviceDiscovery.test.mjs`
Expected: FAIL: `Tree.byCount is not a function`, `offerRepos is not defined`, `service.repos` undefined.

- [ ] **Step 3: Implement `lib/tree.js`**

```javascript
function total(counts) {
  return counts ? KINDS.reduce(function(sum, kind) { return sum + (counts[kind] || 0) }, 0) : null
}

// Largest first. A folder the walk has not reached sits between those with files and those
// without, so it does not jump far when its count lands.
function byCount(rows, countOf) {
  function rank(row) {
    var value = total(countOf(row.path))
    return value === null ? 1 : value > 0 ? 0 : 2
  }
  return rows.slice().sort(function(a, b) {
    var ra = rank(a), rb = rank(b)
    if (ra !== rb) return ra - rb
    if (ra === 0) {
      var diff = total(countOf(b.path)) - total(countOf(a.path))
      if (diff) return diff
    }
    var na = (a.name || a.path).toLowerCase(), nb = (b.name || b.path).toLowerCase()
    return na < nb ? -1 : na > nb ? 1 : a.path < b.path ? -1 : a.path > b.path ? 1 : 0
  })
}

// A repo under a searched folder starts with its code indexed. `proposed` lists repos already
// offered, so one the user switched off stays off; `blocked` are worktrees, whose code the main
// repository already covers.
function addCode(state, repos, proposed, blocked) {
  var code = state.code.slice()
  repos.forEach(function(repo) {
    if (proposed.indexOf(repo.path) >= 0 || code.indexOf(repo.path) >= 0) return
    if (blocked.some(function(folder) { return isInside(repo.path, folder) })) return
    if (searched(repo.path, state)) code.push(repo.path)
  })
  return make(state.chosen, state.skipped, code)
}
```

- [ ] **Step 4: Implement `Service.qml`**

Add `property var repos: ({})` and `property var worktrees: ({})` next to `datasets`. In `clearDiscovery`, clear both the same way as `sets`. In `receiveCounts`, after the datasets block:

```qml
    if (Array.isArray(message.repos)) {
      var nextRepos = Object.assign({}, repos)
      message.repos.forEach(path => nextRepos[path] = {path: path})
      repos = nextRepos
    }
    if (Array.isArray(message.worktrees)) {
      var nextTrees = Object.assign({}, worktrees)
      message.worktrees.forEach(path => nextTrees[path] = {path: path})
      worktrees = nextTrees
    }
```

In the `discover_children` case, also record children with `dir.worktree` into `worktrees` and `dir.repo` into `repos` (same shape), so an expanded worktree is skipped before the walk ends.

- [ ] **Step 5: Implement `ui/SetupFolders.qml`**

Add `property var proposedCode: []`. In `offerDatasets`, build the list from both maps:

```qml
    var found = Object.assign({}, service.datasets, service.worktrees)
    var list = Object.keys(found).filter(path => {
      if (proposed.indexOf(path) >= 0) return false
      var owner = Tree.owner(path, choices)
      return owner.on || owner.path === path
    }).map(path => found[path])
```

Add:

```qml
  function offerRepos() {
    if (!service || !seeded) return
    var list = Object.keys(service.repos || {}).filter(path => proposedCode.indexOf(path) < 0
      && Tree.searched(path, choices)).map(path => service.repos[path])
    if (!list.length) return
    var next = Tree.addCode(choices, list, proposedCode, Object.keys(service.worktrees || {}))
    proposedCode = proposedCode.concat(list.map(entry => entry.path))
    choices = next
  }
```

Change `onChoicesChanged: offerDatasets()` to `onChoicesChanged: { offerDatasets(); offerRepos() }`, call `offerRepos()` after `offerDatasets()` in `seed()`, and in the `Connections` block add `function onWorktreesChanged() { root.offerDatasets() }` and `function onReposChanged() { root.offerRepos() }`.

`ui/DriveDialog.qml`: build its dataset list from `Object.assign({}, service.datasets, service.worktrees)` the same way and add `function onWorktreesChanged() { root.offerDatasets() }`. Drives get no code default.

- [ ] **Step 6: Implement `ui/FolderTree.qml`**

- In `insert`: `var dirs = Tree.byCount(reply ? reply.dirs : [], countOf)`.
- In `reload`: iterate `Tree.byCount(folders, countOf)` instead of `folders`.
- Add a rebuild once per finished walk, keeping focus by path:

```qml
  property var finished: ({})

  function focusedPath() {
    for (var i = 0; i < rows.count; i++) {
      var item = list.itemAtIndex(i)
      if (item && item.focused) return rows.get(i).path
    }
    return ""
  }

  onWalksChanged: {
    var next = Object.assign({}, finished)
    var changed = false
    for (var walkRoot in walks) if (walks[walkRoot].done && !next[walkRoot]) { next[walkRoot] = true; changed = true }
    finished = next
    if (!changed) return
    var path = focusedPath()
    reload()
    var index = path ? indexOf(path) : -1
    if (index < 0) return
    list.positionViewAtIndex(index, ListView.Contain)
    var item = list.itemAtIndex(index)
    if (item) item.focusCheck()
  }
```

- In the delegate: `rule: evidence ? "dataset" : info.worktree ? "worktree" : info.repo ? "repo" : ""` and `action: info.repo && !info.worktree ? "code" : ""`.

- [ ] **Step 7: Implement `ui/RuleTag.qml`**

Header comment: `// \`.tg\`: 16 px rule tag. repo and user accent, worktree cyan, dataset yellow, secrets green with a lock, other rules dim.` Then:

```qml
  readonly property color tone: rule === "user" || rule === "repo" ? Color.accent
    : rule === "worktree" ? Plugin.Palette.cyan
    : (rule === "generated" || rule === "dataset") ? Plugin.Palette.yellow
    : rule === "secrets" ? Plugin.Palette.green
    : Plugin.Tokens.dim
  …
  border.color: rule === "user" || rule === "repo" ? Util.alpha(Color.accent, 0.5)
    : rule === "worktree" ? Util.alpha(Plugin.Palette.cyan, 0.42)
    : (rule === "generated" || rule === "dataset") ? Util.alpha(Plugin.Palette.yellow, 0.42)
    : rule === "secrets" ? Util.alpha(Plugin.Palette.green, 0.42)
    : Plugin.Tokens.sep
```

`docs/DESIGN.md`: extend the tag colour sentence near line 96 to "accent for repos, cyan for worktrees and yellow for datasets".

- [ ] **Step 8: Run all JS tests and qmllint**

Run: `node --test "tests/js/*.test.mjs" && scripts/qmllint.sh`
Expected: all pass, exit 0.

- [ ] **Step 9: Offscreen screenshot**

Use the scratch harness from the previous branch (`~/.local/share/omafind/cache/refinements/scratch/daemon.sh` and `shots.sh`; read both first, they take the worktree path). Create in the fake home `~/omafind-refine-home/Projects/` a repo `main` (`git init`), a worktree `git -C main worktree add ../main-wt`, and a folder with 300 `clip_000001.png`-style files. Capture the Folders step expanded at `Projects`. Expected: rows ordered by file count, `main` tagged repo in accent with Code on, `main-wt` tagged worktree in cyan and unchecked, the dataset in yellow. Save to `~/.local/share/omafind/cache/polish/shots/folders.png` and look at it.

- [ ] **Step 10: Commit**

```bash
git add lib/tree.js Service.qml ui/FolderTree.qml ui/SetupFolders.qml ui/DriveDialog.qml ui/RuleTag.qml docs/DESIGN.md tests/js/tree.test.mjs tests/js/setupFolders.test.mjs tests/js/serviceDiscovery.test.mjs
git commit -S -m "feat(setup): sort folders by size, skip worktrees and index repo code"
```

---

### Task 9: Image previews switch without a flash

**Files:**
- Modify: `ui/PreviewLayer.qml:39-46, 82-111, 400-409`, `ui/PreviewPane.qml`, `lib/format.js` (add `qtImage`)
- Test: `tests/js/format.test.mjs`, `tests/js/previewPane.test.mjs` (new)

**Interfaces:**
- Produces: `Format.qtImage(path) -> bool` (`.jpg .jpeg .png .gif .webp .bmp`, case-insensitive). `PreviewLayer.mediaReady: bool`. `PreviewPane.swap()`, `PreviewPane.pendingSwap`.

- [ ] **Step 1: Write the failing tests**

`tests/js/format.test.mjs`:

```javascript
test('qtImage accepts formats Qt decodes and rejects the rest', () => {
  const F = load('format.js');
  assert.deepEqual(['a.JPG', 'b.png', 'c.webp', 'd.heic', 'e.tiff', 'f'].map(F.qtImage),
    [true, true, true, false, false, false]);
});
```

`tests/js/previewPane.test.mjs` extracts `show` and `swap` from `ui/PreviewPane.qml` with the same regex approach as `searchView.test.mjs`:

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

function pane() {
  const layer = name => ({ name, item: null, preview: null, shown: false, mediaReady: false });
  const first = layer('first'), second = layer('second');
  const gate = { running: false, restart() { this.running = true; }, stop() { this.running = false; } };
  const ctx = vm.createContext({ first, second, front: true, preview: null, gate,
    get current() { return ctx.front ? first : second; } });
  const source = readFileSync(new URL('../../ui/PreviewPane.qml', import.meta.url), 'utf8');
  for (const match of source.matchAll(/^  function \w+\([^]*?^  \}/gm)) vm.runInContext(match[0], ctx);
  return ctx;
}

test('the fade waits for the incoming image and rapid switches show the last selection', () => {
  const ctx = pane();
  ctx.first.item = { id: 'a' }; ctx.first.shown = true;
  ctx.show({ id: 'b' });
  assert.equal(ctx.gate.running, true);
  assert.equal(ctx.first.shown, true);
  ctx.show({ id: 'c' });
  ctx.show({ id: 'd' });
  ctx.second.mediaReady = true;
  ctx.swap();
  assert.equal(ctx.current.item.id, 'd');
  assert.equal(ctx.current.shown, true);
  assert.equal(ctx.first.shown, false);
});
```

Name it `rapid switches show the last selection` (Review Focus 5) or keep the combined name and add that phrase.

- [ ] **Step 2: Run them to verify they fail**

Run: `node --test tests/js/format.test.mjs tests/js/previewPane.test.mjs`
Expected: FAIL: `F.qtImage is not a function`; `ctx.gate.running` is undefined / `swap` not defined.

- [ ] **Step 3: Implement `lib/format.js`**

```javascript
function qtImage(path) {
  return /\.(jpe?g|png|gif|webp|bmp)$/i.test(path || "")
}
```

- [ ] **Step 4: Implement `ui/PreviewPane.qml`**

Replace `show` and add `swap`, a gate timer and a readiness connection:

```qml
  function show(next) {
    var layer = current
    if (!next) {
      gate.stop()
      first.shown = false
      second.shown = false
      return
    }
    if (layer.item && layer.item.id === next.id) {
      gate.stop()
      layer.item = next
      layer.shown = true
      return
    }
    var incoming = front ? second : first
    incoming.preview = preview && preview.id === next.id ? preview : null
    incoming.item = next
    if (incoming.mediaReady) swap()
    else gate.restart()
  }

  // Swaps layers once the incoming one has its picture, or after 150 ms at the latest.
  function swap() {
    gate.stop()
    var incoming = front ? second : first
    current.shown = false
    incoming.shown = true
    front = !front
  }

  Timer {
    id: gate
    interval: 150
    onTriggered: root.swap()
  }

  Connections {
    target: root.front ? second : first
    function onMediaReadyChanged() {
      if (gate.running && (root.front ? second : first).mediaReady) root.swap()
    }
  }
```

The test's `gate` stub stands in for the Timer.

- [ ] **Step 5: Implement `ui/PreviewLayer.qml`**

- Add `import "../lib/format.js" as Format` if missing.
- Replace the `fullFailed` reset and `imageSource`:

```qml
  property bool fullFailed: false
  onPreviewChanged: fullFailed = false
  onItemChanged: fullFailed = false
  readonly property string imageSource: {
    var direct = kind === "image" && !offline && !fullFailed && Format.qtImage(entry.path) ? entry.path : ""
    var full = preview && preview.image && !fullFailed ? preview.image : ""
    var path = direct || full || entry.thumb || ""
    return path ? Util.fileUrl(path) : ""
  }
  readonly property bool mediaReady: imageSource === "" || kind === "audio"
    || (kind === "text" || kind === "code") || (kind === "pdf" ? page.status !== Image.Loading
      : frame.status !== Image.Loading)
```

- `frame` Image: add `retainWhileLoading: true`, set `mipmap: false`, and replace its error handler with `onStatusChanged: if (status === Image.Error && String(source) !== Util.fileUrl(root.entry.thumb || "")) root.fullFailed = true`.
- Fallback icon: `visible: (frame.status === Image.Error || root.imageSource === "") && root.kind !== "video"`.
- PDF Image (line ~400): give it `id: page`, add `retainWhileLoading: true`, set `mipmap: false`.

- [ ] **Step 6: Run the JS tests and qmllint**

Run: `node --test "tests/js/*.test.mjs" && scripts/qmllint.sh`
Expected: all pass, exit 0. If qmllint rejects `retainWhileLoading`, confirm with `grep -rn retainWhileLoading /usr/lib/qt6/qml/QtQuick/plugins.qmltypes` that the installed Qt has it before changing anything.

- [ ] **Step 7: Offscreen check**

With the dev daemon and harness (Task 8 Step 9), index the scratch home's images, search `img:` and switch between three results while capturing about ten frames per switch (`shots.sh` takes a frame interval; read it). Expected: no frame shows the fallback icon; each switch goes from one complete picture to the next. Save to `~/.local/share/omafind/cache/polish/shots/switch-*.png` and look at them.

- [ ] **Step 8: Commit**

```bash
git add lib/format.js ui/PreviewPane.qml ui/PreviewLayer.qml tests/js/format.test.mjs tests/js/previewPane.test.mjs
git commit -S -m "fix(overlay): keep the last picture until the next one is decoded"
```

---

### Task 10: Sharper thumbnails and video frames

**Files:**
- Modify: `helper/omafindd/extractors.py:225-228`, `helper/omafindd/preview.py:172-185`
- Test: `tests/helper/test_image.py:23-41`, `tests/helper/test_preview.py`

**Interfaces:**
- Produces: thumbnails at most 600 px on the long side, JPEG quality 90. Video preview argv uses `scale='min(1024,iw)':-2` and `-q:v 2`, cache key includes `q2`.

- [ ] **Step 1: Write the failing tests**

In `tests/helper/test_image.py` change the expected thumbnail size in `test_exif_orientation_resize_and_thumbnail` from `b"96 128"` to the fixture's size scaled to fit 600 (read the fixture's source size in that test; for a source of 96x128 or smaller, the thumb keeps its size, since `-thumbnail 600x600>` never enlarges). Add:

```python
def test_thumbnail_is_at_most_600_and_quality_90(tmp_path):
    from omafindd.extractors import _thumbnail
    from support.corpus import command

    source = tmp_path / "big.png"
    command("magick", "-size", "1600x1200", "xc:gray", str(source))
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(_thumbnail(str(source)))
    assert command("magick", "identify", "-format", "%w %h %Q", str(thumb)) == b"600 450 90"
```

(Use whatever helper `test_image.py` already uses to run `magick`; `command` above stands for it.)

In `tests/helper/test_preview.py`, find the test that records the ffmpeg argv for video (`grep -n ffmpeg tests/helper/test_preview.py`) and assert the argv contains `"scale='min(1024,iw)':-2"` and `"-q:v", "2"` adjacent.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --project helper pytest tests/helper/test_image.py tests/helper/test_preview.py -q`
Expected: FAIL on the size/quality and the argv.

- [ ] **Step 3: Implement**

`extractors.py`:

```python
def _thumbnail(source: str, *, data=None) -> bytes:
    return _media_command(
        ["magick", source, "-auto-orient", "-thumbnail", "600x600>", "-quality", "90", "jpg:-"],
        data=data,
    )
```

`preview.py`, in `render` for pdf and video:

```python
        side = RENDER_SIDE if kind == "pdf" else 1024
        key = side if kind == "pdf" else f"{side}q2"
        image = paths.preview_dir() / (
            _cache_key(path, jump, key) + (".png" if kind == "pdf" else ".jpg"))
```

and the ffmpeg argv:

```python
                _run(["ffmpeg", "-v", "error", "-ss", str(jump), "-i", str(path),
                      "-frames:v", "1", "-vf", f"scale='min({side},iw)':-2", "-q:v", "2",
                      "-y", str(temporary)])
```

- [ ] **Step 4: Run the tests**

Run: `uv run --project helper pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add helper/omafindd/extractors.py helper/omafindd/preview.py tests/helper/test_image.py tests/helper/test_preview.py
git commit -S -m "fix(omafindd): store larger thumbnails and near-lossless video frames"
```

---

### Task 11: Neovim opens on the line

**Files:**
- Modify: `helper/omafindd/opener.py:28-33` (only if the probe shows `+N` is lost)
- Test: `tests/helper/test_opener.py:13-40`

- [ ] **Step 1: Ask the owner, then probe**

This flashes a terminal window on the owner's desktop. Ask first: "May I open one terminal window for about a second to see which arguments reach the editor?" After a yes:

```bash
P=~/.local/share/omafind/cache/polish; mkdir -p $P
printf '#!/bin/sh\nprintf "%%s\\n" "$@" > %s/argv\n' "$P" > $P/argv.sh; chmod +x $P/argv.sh
xdg-terminal-exec --app-id=org.omarchy.probe -e $P/argv.sh +42 /tmp/x.md
sleep 2; cat $P/argv
```

Expected output, if the terminal keeps the arguments: `+42` then `/tmp/x.md`.

- [ ] **Step 2: Decide**

- If `+42` is missing or changed: repeat Step 1 with `-c 42 /tmp/x.md` in place of `+42 /tmp/x.md`, then with `/tmp/x.md +42`. Use the first form that arrives intact.
- If `+42` arrives intact: the line is lost inside Neovim's start in a real terminal. Report this to the owner with the probe output, skip Steps 3 to 5, and leave the opener unchanged.

- [ ] **Step 3: Write the failing test** for the chosen form, for example `-c`:

```python
        ("nvim", ["-c", "41", "/tmp/a.txt"]),
        ("vim", ["-c", "41", "/tmp/a.txt"]),
```

in the `test_text_editor_line_arguments` table (nano and micro keep `+41`; only vim and nvim accept `-c`).

- [ ] **Step 4: Implement**

```python
            if editor in ("nvim", "vim"):
                return ["omarchy-launch-editor", "-c", str(line), path]
            if editor in ("nano", "micro"):
                return ["omarchy-launch-editor", f"+{line}", path]
```

Check `description()` (`opener.py:71-98`): its `len(argv) > 2` test for showing "nvim +N" must still be true for the new argv, and the label must still read `nvim +41`. Run `uv run --project helper pytest tests/helper/test_opener.py tests/helper/test_preview.py -q`; all pass.

- [ ] **Step 5: Commit**

```bash
git add helper/omafindd/opener.py tests/helper/test_opener.py
git commit -S -m "fix(omafindd): pass the line to vim and neovim in a form terminals keep"
```

---

### Task 12: Faster indexing, measured

**Files:**
- Modify: `helper/omafindd/jobs.py:103-255`
- Create: `scripts/time-index.sh` is NOT added to the repo; timing scripts live in `~/.local/share/omafind/cache/polish/`
- Test: `tests/helper/test_jobs.py`

**Interfaces:**
- Consumes: `Embedder` semaphore (Task 4), `EmbeddingRejected` (Task 3).
- Produces: `Jobs.drain` with `prefetch=4` keyword (number of extractions in flight). Behaviour and committed state per file unchanged.

- [ ] **Step 1: Baseline timing**

Build a fixed corpus once: `tests/fixtures/corpus` copied to `~/omafind-refine-home/Bench/` plus 200 Markdown files generated by:

```bash
B=~/omafind-refine-home/Bench/notes; mkdir -p $B
for n in $(seq 1 200); do python3 -c "import random,sys; random.seed($n); w=open('/usr/share/dict/words').read().split() if __import__('os').path.exists('/usr/share/dict/words') else ['alpha','beta','gamma','delta','omega']; print(' '.join(random.choice(w) for _ in range(300)))" > $B/note-$n.md; done
```

With the dev daemon stopped, time a clean index of only that folder in the capped scope (read `scratch/daemon.sh` for the env it sets: scratch `HOME`, `XDG_RUNTIME_DIR=/run/user/1000/ofdev`, the venv link). Remove the scratch index dir before each run so every file is embedded:

```bash
systemd-run --user --scope --quiet --collect -p MemoryMax=8G -p MemorySwapMax=0 -- \
  env HOME=$HOME/omafind-refine-home XDG_RUNTIME_DIR=/run/user/1000/ofdev \
  /usr/bin/time -f '%e s %M KB' bin/omafind reindex
```

Run it three times and record the median in `~/.local/share/omafind/cache/polish/timing.txt`. Check `pgrep -x llama-server` shows only the live one afterwards.

- [ ] **Step 2: Write the failing test** (extraction overlaps embedding)

```python
async def test_next_files_are_extracted_while_one_embeds(store, tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from omafindd import jobs
    from omafindd.extractors import Extracted, Segment

    for n in range(4):
        (tmp_path / f"n{n}.txt").write_text(f"note {n}")
    crawl(store, [{"path": str(tmp_path)}])
    started = []
    lock = threading.Lock()

    def extract(path, kind, start):
        with lock:
            started.append(path.name)
        return Extracted([Segment("chunk", "text", path.name, 1, 1)])

    class Slow(FakeEmbedder):
        async def embed_documents(self, parts):
            if len(started) < 4:
                await asyncio.sleep(0.05)
            snapshot.append(len(started))
            return await super().embed_documents(parts)

    snapshot = []
    monkeypatch.setattr(jobs, "extract", extract)
    monkeypatch.setattr(jobs, "_pool", lambda: ThreadPoolExecutor(4))
    await jobs.Jobs(store, Slow(), journal=tmp_path / "journal").drain()
    assert snapshot[0] >= 2
    assert {row[0] for row in store.db.execute("SELECT state FROM files")} == {"done"}
```

`test_pdf_windows_are_committed_before_next_extraction` must keep passing: windows of one file are never prefetched, because the next window is only selected after the current one is written.

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run --project helper pytest tests/helper/test_jobs.py -q -k extracted_while`
Expected: FAIL: `snapshot[0] == 1`.

- [ ] **Step 4: Implement prefetch**

Restructure the inner loop of `drain` so extraction is submitted ahead:

```python
                pending = {}

                def submit(row):
                    info = json.loads(row["info"] or "{}")
                    append = row["state"] == "partial" and row["detail"] is None
                    start = (info.get("read_to", 0) if row["kind"] == "pdf"
                             else info.get("audio_next", 0)) + 1 if append else 1
                    args = [self.store.mount / row["path"], row["kind"], start]
                    if row["kind"] in ("image", "video", "audio"):
                        args.extend([self.settings.audio, self.settings.image_budget])
                    if row["kind"] == "video":
                        args.append(info.get("frame_next") if append else 0.0)
                    pending[row["id"]] = (pool.submit(extract, *args), info, append)

                ordered = [dict(row) for row in rows]
                for row in ordered[:prefetch]:
                    submit(row)
                for index, row in enumerate(ordered):
                    if index + prefetch < len(ordered):
                        submit(ordered[index + prefetch])
                    future, info, append = pending.pop(row["id"])
                    ...existing per-file body, with `future` taken from here instead of
                    calling pool.submit, and `result = await asyncio.wrap_future(future)`...
```

Keep the existing `BrokenProcessPool` handling: on a broken pool, shut it down, rebuild it, fail the current file, and resubmit every entry still in `pending` to the new pool. Remove the `self.queue` put/get pair if nothing else reads `self.queue` (`grep -n "queue" helper/omafindd/*.py`); otherwise keep it in step with the loop. Add `prefetch: int = 4` to the `drain` signature.

- [ ] **Step 5: Run the job tests**

Run: `uv run --project helper pytest tests/helper/test_jobs.py tests/helper/test_recovery.py -q`
Expected: all pass.

- [ ] **Step 6: Time it again**

Repeat Step 1's three runs and record the median. Watch the scope's `MemoryPeak` once with `systemctl --user show <scope> -p MemoryPeak`.

- [ ] **Step 7: Keep or revert**

- If the median improved by 15 % or more, commit:

```bash
git add helper/omafindd/jobs.py tests/helper/test_jobs.py
git commit -S -m "perf(omafindd): extract the next files while one embeds"
```

- If not, `git restore helper/omafindd/jobs.py tests/helper/test_jobs.py`, record the numbers, and skip Steps 8 to 10.

- [ ] **Step 8 (only if Step 7 kept prefetch): cross-file text batching**

Write a failing test: ten one-chunk text files lead to at most one `embed_documents` call of ten parts per 16 inputs (count calls in a `FakeEmbedder` subclass). Then, in `drain`, gather consecutive text rows whose extraction is ready and whose combined segment count stays at most 16, embed their parts in one call, split the vectors back by each file's segment count, and write each file with its own `store.write`. A rejected batch (`EmbeddingRejected`) is retried one file at a time, so only the bad file fails.

- [ ] **Step 9: Time it again** as in Step 1. Keep it if it improves the median by at least 5 % over Step 6; otherwise restore `jobs.py` to the Step 7 commit.

- [ ] **Step 10: Commit if kept**

```bash
git add helper/omafindd/jobs.py tests/helper/test_jobs.py
git commit -S -m "perf(omafindd): send small text files to the server together"
```

Record all medians for the PR body.

---

### Task 13: Docs, full checks and the live hand-off

**Files:**
- Modify: `docs/ipc.md`, `README.md`

- [ ] **Step 1: Update `docs/ipc.md`**

- `discover_counts`: the final batch (and a done snapshot) carries `repos` and `worktrees`, sorted lists of absolute paths.
- `discover_start`/`discover_children` rows: add `worktree` (bool); `repo` is false for a worktree.
- `results` for `kinds: ["code"]`: optional `notice: "no-code-index"` when no code index exists; `degraded` stays null.
- File details: add `embedding-failed` (failed file, or a halted `partial` file).

- [ ] **Step 2: Update `README.md`**: where it describes code search or the Folders step, say repositories under picked folders are indexed as code by default and worktrees are left out. No settings table change.

- [ ] **Step 3: Run every check**

```bash
uv run --project helper pytest -q
node --test "tests/js/*.test.mjs"
uv run --project helper ruff check helper tests bin/omafind scripts evals
scripts/qmllint.sh
```

Expected: all pass. Read the output; record the counts for the PR.

- [ ] **Step 4: Commit**

```bash
git add docs/ipc.md README.md
git commit -S -m "docs: describe worktrees, code notices and embedding failures"
```

- [ ] **Step 5: Hand-off for live checks** (the owner repoints the plugin and restarts the daemon; do not do it yourself). Give the owner these commands and what to expect:

```bash
P=$(systemctl --user show omafind.service -p MainPID --value)
ls -l /proc/$P/fd | grep -c inotify      # expect 1
ls /proc/$P/task | wc -l                   # expect tens, not about 1,900
journalctl --user -u omafind.service --since -10min | grep -c 'errno=24'   # expect 0
```

Then: the stuck PDF either finishes or shows as halted with `embedding-failed`; re-open setup to get Code on for repos, run the index, and `code: <something in a repo>` returns hits.

- [ ] **Step 6: Clean up**

Stop the dev daemon. `pgrep -x llama-server` lists only the live daemon's server. Leave `~/omafind-refine-home` and the cache folders for the owner.
