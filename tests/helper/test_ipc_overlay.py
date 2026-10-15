import json
import sqlite3
from types import SimpleNamespace

import pytest
from omafindd import errors, opener, preview
from omafindd.ipc import IpcServer
from omafindd.settings import Settings
from omafindd.state import State


class Writer:
    def __init__(self):
        self.messages = []

    def write(self, data):
        self.messages.append(json.loads(data))

    async def drain(self):
        pass


@pytest.fixture
def server(tmp_path, monkeypatch):
    import asyncio

    async def inline(function, *args):
        return function(*args)

    monkeypatch.setattr(asyncio, "to_thread", inline)
    return IpcServer(tmp_path / "ui.sock", State())


@pytest.mark.parametrize("kind,mode", [("text", "lines"), ("code", "lines"),
                                      ("pdf", "image"), ("video", "image"),
                                      ("image", "image"), ("audio", "bars")])
async def test_preview_latest_results(server, tmp_path, monkeypatch, kind, mode):
    path = tmp_path / "fixture"
    path.touch()
    item = {"id": "hit", "kind": kind, "path": str(path), "loc": 1}

    async def handle(message):
        return {"t": "results", "items": [item]}

    server.service = SimpleNamespace(handle=handle)
    writer = Writer()
    await server.dispatch(writer, {"t": "search"})
    calls = []

    def render(value, query):
        calls.append((value, query))
        return {"t": "preview", "id": value["id"], "mode": mode, "jump": 212}

    monkeypatch.setattr(preview, "render", render)
    await server.dispatch(writer, {"t": "preview", "id": "hit", "q": "talk"})
    assert writer.messages[-1]["mode"] == mode
    assert calls == [(item, "talk")]
    other = Writer()
    await server.dispatch(other, {"t": "preview", "id": "hit"})
    assert other.messages[-1] == {"t": "error", "id": "hit",
                                  **errors.file_missing("The file").to_dict()}


async def test_preview_failure_is_internal_with_the_item_id(server, tmp_path, monkeypatch):
    path = tmp_path / "a.pdf"
    path.touch()
    writer = Writer()
    server._results[writer] = {"hit": {"id": "hit", "kind": "pdf", "path": str(path)}}

    def render(item, query):
        raise RuntimeError("pdftoppm crashed")

    monkeypatch.setattr(preview, "render", render)
    await server.dispatch(writer, {"t": "preview", "id": "hit"})
    assert writer.messages[-1] == {"t": "error", "id": "hit",
                                   **errors.internal("pdftoppm crashed").to_dict()}


async def test_open_reveal_and_preview_jump(server, tmp_path, monkeypatch):
    path = tmp_path / "a.txt"
    path.touch()
    writer = Writer()
    item = {"id": "hit", "kind": "text", "path": str(path), "loc": 205}
    server._results[writer] = {"hit": item}
    calls = []
    monkeypatch.setattr(preview, "render", lambda item, query: {
        "t": "preview", "id": "hit", "jump": 212, "mode": "lines"})
    monkeypatch.setattr(opener, "launch", lambda item, **kw: calls.append((item, kw)))
    await server.dispatch(writer, {"t": "preview", "id": "hit", "q": "talk"})
    await server.dispatch(writer, {"t": "open", "id": "hit", "how": "open"})
    assert writer.messages[-1]["t"] == "opened"
    assert writer.messages[-1]["at"] == "L212"
    assert calls[-1][0]["loc"] == 212
    await server.dispatch(writer, {"t": "open", "id": "hit", "how": "reveal"})
    assert writer.messages[-1]["opener"] == "nautilus --select"
    assert calls[-1][1]["how"] == "reveal"


@pytest.mark.parametrize("offline,exists,error", [
    (True, True, errors.drive_not_mounted("Photos2024")),
    (False, False, errors.file_missing("a")),
])
async def test_open_refuses_offline_or_missing(server, tmp_path, monkeypatch,
                                              offline, exists, error):
    path = tmp_path / "a"
    if exists:
        path.touch()
    writer = Writer()
    server._results[writer] = {"hit": {"id": "hit", "path": str(path), "offline": offline,
                                       "label": "Photos2024"}}
    monkeypatch.setattr(opener, "launch", lambda *args, **kw: pytest.fail("launched"))
    await server.dispatch(writer, {"t": "open", "id": "hit", "how": "open"})
    assert writer.messages[-1] == {"t": "open_failed", "id": "hit", "error": error.to_dict()}
    await server.dispatch(writer, {"t": "open", "id": "unknown", "how": "open"})
    assert writer.messages[-1]["error"] == errors.file_missing("The file").to_dict()


async def test_open_launch_failure_names_the_program(server, tmp_path, monkeypatch):
    path = tmp_path / "clip.mp4"
    path.touch()
    writer = Writer()
    server._results[writer] = {"hit": {"id": "hit", "kind": "video", "path": str(path)}}

    def launch(item, **kw):
        raise FileNotFoundError(2, "No such file or directory", "mpv")

    monkeypatch.setattr(opener, "launch", launch)
    await server.dispatch(writer, {"t": "open", "id": "hit", "how": "open"})
    assert writer.messages[-1] == {
        "t": "open_failed", "id": "hit",
        "error": errors.open_failed("clip.mp4", "mpv: No such file or directory").to_dict()}


async def test_status_reply_and_time_gated_push(server, tmp_path):
    db = sqlite3.connect(tmp_path / "v.sqlite")
    db.execute("CREATE TABLE files(state TEXT, detail TEXT, indexed_at REAL)")
    db.executemany("INSERT INTO files VALUES(?,NULL,?)", [("done", 1), ("pending", None)])
    db.commit()
    server.service = SimpleNamespace(directory=tmp_path, settings=lambda: Settings(roots=[{}]))
    writer = Writer()
    server._ready.add(writer)
    await server.dispatch(writer, {"t": "status"})
    assert writer.messages[-1] == {"t": "status", "files": 1, "roots": 1,
                                   "offline": [], "done": 1, "total": 2}
    await server.push_status(now=0)
    for i in range(1, 20):
        db.execute("INSERT INTO files VALUES('pending',NULL,NULL)")
        db.commit()
        await server.push_status(now=i / 20)
    assert len(writer.messages) == 3
    db.execute("UPDATE files SET state='done',indexed_at=1")
    db.commit()
    await server.push_status(now=1)
    assert writer.messages[-1]["done"] == writer.messages[-1]["total"] == 21
    count = len(writer.messages)
    await server.push_status(now=2)
    assert len(writer.messages) == count
    db.close()


def test_detached_nautilus_launcher(monkeypatch):
    calls = []
    monkeypatch.setattr(opener.subprocess, "Popen", lambda argv, **kw: calls.append((argv, kw)))
    opener.launch({"kind": "image", "path": "/fake"}, how="reveal")
    assert calls[0][0][-3:] == ["nautilus", "--select", "/fake"]
    assert calls[0][1]["start_new_session"]


async def test_preview_serializes_renders_and_skips_superseded_requests(
    server, tmp_path, monkeypatch
):
    import asyncio

    writer = Writer()
    path = tmp_path / "file"
    path.touch()
    server._results[writer] = {key: {"id": key, "kind": "text", "path": str(path)}
                               for key in ("old", "pending", "latest")}
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    active = 0

    async def render(function, item, query):
        nonlocal active
        active += 1
        assert active == 1
        calls.append(item["id"])
        if item["id"] == "old":
            started.set()
            await release.wait()
        active -= 1
        return {"t": "preview", "id": item["id"], "jump": 12}

    monkeypatch.setattr(asyncio, "to_thread", render)
    old = asyncio.create_task(server.dispatch(writer, {"t": "preview", "id": "old"}))
    await started.wait()
    pending = asyncio.create_task(server.dispatch(writer, {"t": "preview", "id": "pending"}))
    latest = asyncio.create_task(server.dispatch(writer, {"t": "preview", "id": "latest"}))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(old, pending, latest)
    assert calls == ["old", "latest"]
    assert writer.messages == [{"t": "preview", "id": "latest", "jump": 12}]
    assert server._jumps[writer] == {"latest": 12}


@pytest.mark.parametrize("same_path,expected", [(True, "preview"), (False, "error")])
async def test_preview_survives_a_later_reply_that_rebuilds_items(
    server, tmp_path, monkeypatch, same_path, expected
):
    import asyncio

    writer = Writer()
    path, other = tmp_path / "file", tmp_path / "other"
    path.touch()
    other.touch()
    server._results[writer] = {"a": {"id": "a", "kind": "text", "path": str(path)}}
    started, release = asyncio.Event(), asyncio.Event()

    async def render(function, item, query):
        started.set()
        await release.wait()
        return {"t": "preview", "id": item["id"], "jump": 3}

    monkeypatch.setattr(asyncio, "to_thread", render)
    task = asyncio.create_task(server.dispatch(writer, {"t": "preview", "id": "a"}))
    await started.wait()
    rebuilt = str(path if same_path else other)
    server._results[writer] = {"a": {"id": "a", "kind": "text", "path": rebuilt}}
    release.set()
    await task
    assert writer.messages[-1]["t"] == expected


async def test_status_runs_off_event_loop(server, monkeypatch):
    import asyncio

    calls = []

    async def threaded(function, *args):
        calls.append(function)
        return function(*args)

    monkeypatch.setattr(asyncio, "to_thread", threaded)
    await server.dispatch(Writer(), {"t": "status"})
    await server.push_status(now=0)
    assert calls == [server.status_message, server.status_message]


def test_status_caches_store_and_wal_mtimes_and_closes_on_error(server, tmp_path, monkeypatch):
    import os

    path = tmp_path / "v.sqlite"
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE files(state TEXT, detail TEXT, indexed_at REAL)")
    db.commit()
    server.service = SimpleNamespace(directory=tmp_path, settings=lambda: Settings())
    connect = sqlite3.connect
    connections = []

    def tracked(*args, **kwargs):
        value = connect(*args, **kwargs)
        connections.append(value)
        return value

    monkeypatch.setattr(sqlite3, "connect", tracked)
    try:
        assert server.status_message()["files"] == 0
        server.status_message()
        assert len(connections) == 1
        server.service.settings = lambda: Settings(roots=[{}])
        assert server.status_message()["roots"] == 1
        assert len(connections) == 1
        db.execute("INSERT INTO files VALUES('done',NULL,1)")
        db.commit()
        assert server.status_message()["files"] == 1
        assert len(connections) == 2
        db.execute("DROP TABLE files")
        db.commit()
        server.status_message()
        for connection in connections:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                connection.execute("SELECT 1")
        os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1))
        server.status_message()
        assert len(connections) == 4
    finally:
        db.close()


async def test_cancelled_preview_holds_slot_until_renderer_finishes(server, tmp_path, monkeypatch):
    import asyncio

    writer = Writer()
    path = tmp_path / "file"
    path.touch()
    server._results[writer] = {key: {"id": key, "kind": "text", "path": str(path)}
                               for key in ("old", "latest")}
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def render(function, item, query):
        calls.append(item["id"])
        if item["id"] == "old":
            started.set()
            await release.wait()
        return {"t": "preview", "id": item["id"], "jump": 12}

    monkeypatch.setattr(asyncio, "to_thread", render)
    old = asyncio.create_task(server.dispatch(writer, {"t": "preview", "id": "old"}))
    await started.wait()
    old.cancel()
    latest = asyncio.create_task(server.dispatch(writer, {"t": "preview", "id": "latest"}))
    await asyncio.sleep(0)
    assert calls == ["old"]
    release.set()
    await asyncio.gather(old, latest, return_exceptions=True)
    assert calls == ["old", "latest"]
    assert writer.messages == [{"t": "preview", "id": "latest", "jump": 12}]


async def test_meaning_leg_keeps_jump_and_new_seq_drops_it(server, tmp_path, monkeypatch):
    path = tmp_path / "a.txt"
    path.touch()
    item = {"id": "hit", "kind": "text", "path": str(path), "loc": 205}
    other = {"id": "gone", "kind": "text", "path": str(path), "loc": 1}
    replies = []

    async def handle(message):
        return replies.pop(0)

    server.service = SimpleNamespace(handle=handle)
    writer = Writer()
    replies.append({"t": "results", "seq": 4, "legs": ["words"], "items": [item, other]})
    await server.dispatch(writer, {"t": "search", "seq": 4})
    monkeypatch.setattr(preview, "render", lambda value, query: {
        "t": "preview", "id": value["id"], "jump": 212, "mode": "lines"})
    await server.dispatch(writer, {"t": "preview", "id": "hit", "q": "talk"})
    await server.dispatch(writer, {"t": "preview", "id": "gone", "q": "talk"})
    replies.append({"t": "results", "seq": 4, "legs": ["words", "meaning"], "items": [item]})
    await server.dispatch(writer, {"t": "search", "seq": 4})
    assert server._jumps[writer] == {"hit": 212}
    replies.append({"t": "results", "seq": 5, "legs": ["words"], "items": [item]})
    await server.dispatch(writer, {"t": "search", "seq": 5})
    assert server._jumps.get(writer, {}) == {}


async def test_open_prefers_client_line_and_rejects_bad_lines(server, tmp_path, monkeypatch):
    path = tmp_path / "a.txt"
    path.touch()
    writer = Writer()
    server._results[writer] = {"hit": {"id": "hit", "kind": "text", "path": str(path), "loc": 205}}
    server._jumps[writer] = {"hit": 212}
    calls = []
    monkeypatch.setattr(opener, "launch", lambda item, **kw: calls.append(item))
    await server.dispatch(writer, {"t": "open", "id": "hit", "how": "open", "line": 230})
    assert calls[-1]["loc"] == 230
    await server.dispatch(writer, {"t": "open", "id": "hit", "how": "open"})
    assert calls[-1]["loc"] == 212
    for line in (0, -3, "7", True, 2.5, None):
        await server.dispatch(writer, {"t": "open", "id": "hit", "how": "open", "line": line})
        assert writer.messages[-1] == {
            "t": "error", "id": "hit", "for": "open",
            **errors.bad_request("Invalid open arguments").to_dict()}
    assert len(calls) == 2


@pytest.mark.parametrize("kind,expected", [("code", 230), ("pdf", 3), ("image", None)])
async def test_client_line_only_overrides_text_and_code(server, tmp_path, monkeypatch,
                                                       kind, expected):
    path = tmp_path / "file"
    path.touch()
    writer = Writer()
    item = {"id": "hit", "kind": kind, "path": str(path), "loc": 3 if kind == "pdf" else None}
    if kind == "code":
        item["open_line"] = 8
    server._results[writer] = {"hit": item}
    calls = []
    monkeypatch.setattr(opener, "launch", lambda item, **kw: calls.append(item))
    await server.dispatch(writer, {"t": "open", "id": "hit", "line": 230})
    assert calls[0]["loc"] == expected
    if kind == "code":
        assert calls[0]["open_line"] == 230
    assert item["loc"] == (3 if kind == "pdf" else None)
