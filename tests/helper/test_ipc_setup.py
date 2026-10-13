import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from omafindd.ipc import IpcServer
from omafindd.settings import Settings
from omafindd.setup import SetupService
from omafindd.state import State
from omafindd.store import Store


class Writer:
    def __init__(self):
        self.messages = []

    def write(self, data):
        self.messages.append(json.loads(data))

    async def drain(self):
        pass

    def get_extra_info(self, name):
        return None

    def close(self):
        pass

    async def wait_closed(self):
        pass


class Runtime:
    def __init__(self):
        self.calls = []

    async def status(self):
        self.calls.append("status")
        return {"t": "runtime_progress"}

    async def start(self):
        self.calls.append("start")
        return {"t": "runtime_progress"}

    async def pause(self):
        self.calls.append("pause")
        return {"t": "runtime_progress"}

    async def stop(self):
        self.calls.append("stop")


@pytest.fixture
def service(tmp_path, monkeypatch):
    async def inline(fn, *args, **kw):
        return fn(*args, **kw)

    monkeypatch.setattr(asyncio, "to_thread", inline)
    monkeypatch.setattr("omafindd.setup.mounted_volumes", lambda: {"u": Path("/h")})
    process = SimpleNamespace(pid=987654, returncode=None)
    calls, pushes = [], []

    async def spawn(*args, **kw):
        calls.append((args, kw))
        return process

    async def broadcast(body):
        pushes.append(body)

    scan = SimpleNamespace(body={"candidates": []}, roots={}, scanned_at=123.0)

    def tree(scan, root, *, home):
        absolute = str(home / root[2:]) if root.startswith("~/") else root
        return {"root": root, "abs": absolute, "scanned_at": 123.0, "dirs": []}

    def list_dirs(path, *, home):
        absolute = str(home) if path == "~" else path
        return {"path": path, "abs": absolute, "dirs": ["Documents", "Pictures"], "error": None}

    setup = SetupService(
        data_dir=tmp_path,
        plugin_root=tmp_path / "plugin",
        settings=lambda: Settings(roots=[{"path": "/h/Documents", "volume": "u", "excludes": []}]),
        broadcast=broadcast,
        runtime=Runtime(),
        spawn=spawn,
        discover=lambda **kw: scan,
        tree=tree,
        list_dirs=list_dirs,
        home=Path("/h"),
    )
    setup.test_calls, setup.test_pushes, setup.test_process = calls, pushes, process
    return setup


@pytest.mark.parametrize(
    "kind,method",
    [("runtime_status", "status"), ("runtime_install", "start"), ("runtime_pause", "pause")],
)
async def test_runtime_requests(service, kind, method):
    assert await service.handle({"t": kind}) == {"t": "runtime_progress"}
    assert service.runtime.calls == [method]


async def test_discover_start(service):
    result = await service.handle({"t": "discover_start"})
    assert result == {"t": "discover_result", "candidates": [], "volume": None}


@pytest.mark.parametrize("root", ["~/Documents", "/h/Documents"])
async def test_discover_tree(service, root):
    result = await service.handle({"t": "discover_tree", "root": root})
    assert result["t"] == "discover_tree"
    assert result["root"] == root
    assert result["abs"] == "/h/Documents"


async def test_fs_list(service):
    result = await service.handle({"t": "fs_list", "path": "~"})
    assert result == {
        "t": "fs_list",
        "path": "~",
        "abs": "/h",
        "dirs": ["Documents", "Pictures"],
        "error": None,
    }


async def test_fs_list_missing(service):
    service.list_dirs = lambda path, **kw: {
        "path": path,
        "abs": path,
        "dirs": [],
        "error": "missing",
    }
    assert (await service.handle({"t": "fs_list", "path": "/missing"}))["error"] == "missing"


async def test_index_start_spawns_once(service):
    result = await service.handle({"t": "index_start"})
    assert result["t"] == "progress" and result["running"]
    assert await service.handle({"t": "index_start"}) == result
    assert len(service.test_calls) == 1
    args, kw = service.test_calls[0]
    assert args[1:] == (str(service.plugin_root / "bin/omafind"), "reindex", "--incremental")
    assert kw["start_new_session"]
    assert (service.data_dir / "index/reindex.log").stat().st_mode & 0o777 == 0o600


async def test_index_start_no_roots(service):
    service.settings = lambda: Settings()
    assert await service.handle({"t": "index_start"}) == {
        "t": "error",
        "for": "index_start",
        "code": "no-roots",
        "reason": "No folders are selected. Pick folders in setup first.",
    }
    assert not service.test_calls


async def test_concurrent_discover_start_shares_one_scan(service, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    original = service.discover

    async def delayed(fn, *args, **kw):
        calls.append(fn)
        entered.set()
        await release.wait()
        return fn(*args, **kw)

    monkeypatch.setattr(asyncio, "to_thread", delayed)
    one = asyncio.create_task(service.handle({"t": "discover_start"}))
    await entered.wait()
    two = asyncio.create_task(service.handle({"t": "discover_start"}))
    await asyncio.sleep(0)
    release.set()
    assert await one == await two
    assert calls == [original]


async def test_cancelled_request_does_not_cancel_shared_scan(service, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(fn, *args, **kw):
        entered.set()
        await release.wait()
        return fn(*args, **kw)

    monkeypatch.setattr(asyncio, "to_thread", delayed)
    one = asyncio.create_task(service.handle({"t": "discover_start"}))
    await entered.wait()
    one.cancel()
    with pytest.raises(asyncio.CancelledError):
        await one
    two = asyncio.create_task(service.handle({"t": "discover_start"}))
    release.set()
    assert (await two)["t"] == "discover_result"


async def test_progress_is_rate_limited_to_two_per_second(service):
    await service.handle({"t": "index_start"})
    for now in (0.0, 0.2, 0.6):
        service.test_process.returncode = None
        service._progress = lambda now=now: {"t": "progress", "running": True, "done": now}
        await service.poll(now=now)
    assert [p["done"] for p in service.test_pushes] == [0.0, 0.6]


async def test_final_progress_is_sent_after_exit(service):
    await service.handle({"t": "index_start"})
    await service.poll(now=0.0)
    service.test_process.returncode = 0
    await service.poll(now=0.1)
    await service.poll(now=0.2)
    assert [p["running"] for p in service.test_pushes] == [True, False]
    assert "exit" not in service.test_pushes[-1]


@pytest.mark.parametrize("exit_code", [1, 2, -9])
async def test_failed_index_exit_broadcasts_progress_and_error(service, exit_code):
    await service.handle({"t": "index_start"})
    await service.poll(now=0.0)
    service.test_process.returncode = exit_code
    await service.poll(now=0.1)
    await service.poll(now=0.2)
    assert [p["t"] for p in service.test_pushes] == ["progress", "progress", "error"]
    final, error = service.test_pushes[-2:]
    assert final["running"] is False
    assert final["exit"] == exit_code
    assert error == {
        "t": "error",
        "for": "index_start",
        "code": "runtime-failed",
        "reason": f"Indexing exited with code {exit_code}. "
        f"See {service.data_dir / 'index/reindex.log'}.",
    }


async def test_errors_carry_for_and_no_seq(service, tmp_path):
    def failed(**kw):
        raise OSError("scan broke")

    service.discover = failed
    server = IpcServer(tmp_path / "ui.sock", State(), setup=service)
    writer = Writer()
    await server.dispatch(writer, {"t": "discover_start", "seq": 7, "id": "wrong"})
    assert writer.messages == [
        {"t": "error", "for": "discover_start", "code": "scan-failed", "reason": "scan broke"}
    ]


@pytest.mark.parametrize("kind", sorted(SetupService.TYPES))
async def test_setup_messages_are_ignored_before_hello(service, tmp_path, kind):
    server = IpcServer(tmp_path / "ui.sock", State(), setup=service, peer_uid=lambda _: os.getuid())
    reader = asyncio.StreamReader()
    reader.feed_data((json.dumps({"t": kind}) + "\n").encode())
    reader.feed_eof()
    writer = Writer()
    await server._client(reader, writer)
    assert not writer.messages
    assert not service.runtime.calls


async def test_progress_body_from_stores(service):
    path = service.data_dir / "index/u.sqlite"
    store = Store(path, volume="u", mount=Path("/h"))
    rows = [
        ("a.txt", "text", "pending", None, {}),
        ("b.pdf", "pdf", "done", None, {"pages": 12}),
        ("Pictures/c.png", "image", "done", None, {}),
        ("Pictures/d.png", "image", "done", None, {}),
        ("e.pdf", "pdf", "failed", "encrypted-pdf", {}),
        ("f.mp4", "video", "partial", None, {}),
        ("g.mp4", "video", "partial", "bad-soundtrack", {}),
        ("Pictures/h.png", "image", "done", None, {}),
    ]
    for index, (path, kind, state, detail, info) in enumerate(rows, 1):
        store.db.execute(
            "INSERT INTO files(id,path,kind,size,mtime,inode,device,"
            "state,detail,info) "
            "VALUES(?,?,?,0,0,0,0,?,?,?)",
            (index, path, kind, state, detail, json.dumps(info)),
        )
        store.name_row(index, path)
    # Segment IDs intentionally differ from file IDs (Store.name_row keys fts by segment).
    store.db.execute("INSERT INTO segments(id,file,kind,modality) VALUES(80,3,'ocr','none')")
    store.db.execute("INSERT INTO fts(rowid,name,body) VALUES(80,'','words')")
    store.db.commit()
    store.close()
    (service.data_dir / "index/run.json").write_text(
        json.dumps({"pid": 987654, "skipped": {"size-cap": 2, "dataset": 0}})
    )
    service._scan = SimpleNamespace(
        body={
            "candidates": [{"path": "/h/Documents", "left_out": [{"rule": "secrets", "files": 3}]}]
        },
        roots={},
    )
    result = await service.handle({"t": "index_start"})
    assert result["kinds"] == {
        "text": {"done": 0, "total": 1},
        "pdf": {"done": 2, "total": 2, "pages": 12},
        "image": {"done": 3, "total": 3, "ocr": 1},
        "video": {"done": 1, "total": 2},
        "audio": {"done": 0, "total": 0},
    }
    assert result["done"] == 6 and result["queued"] == 2
    assert result["skipped"] == {"size-cap": 2, "secrets": 3}
    assert result["failed"] == {"encrypted-pdf": 1}
    assert result["problems"] == [{"path": "/h/e.pdf", "reason": "encrypted-pdf"}]
    assert result["volume"] == "u"
    assert result["volumes"] == {"u": {"label": "root", "done": 6, "total": 8}}


@pytest.mark.parametrize(
    "message",
    [{"t": "discover_tree"}, {"t": "fs_list", "path": 2}, {"t": "discover_start", "volume": []}],
)
async def test_bad_request(service, message):
    result = await service.handle(message)
    assert result["code"] == "bad-request" and result["for"] == message["t"]


async def test_disconnected_index_request_keeps_spawned_job(service):
    entered, release = asyncio.Event(), asyncio.Event()
    original = service.spawn

    async def blocked(*args, **kw):
        entered.set()
        await release.wait()
        return await original(*args, **kw)

    service.spawn = blocked
    request = asyncio.create_task(service.handle({"t": "index_start"}))
    await entered.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    release.set()
    for _ in range(10):
        await asyncio.sleep(0)
    assert service._index is service.test_process
    assert len(service.test_calls) == 1


async def test_setup_stop_terminates_child_process_group(service, monkeypatch):
    await service.handle({"t": "index_start"})
    killed = []

    async def wait():
        service.test_process.returncode = -15
        return -15

    service.test_process.wait = wait
    monkeypatch.setattr(os, "killpg", lambda *args: killed.append(args))
    await service.stop()
    assert killed[0][0] == service.test_process.pid
    assert service.runtime.calls == ["stop"]


async def test_ipc_dispatch_exception_uses_for_without_search_sequence(service, tmp_path):
    async def broken(message):
        raise ValueError("bad service")

    service.handle = broken
    server = IpcServer(tmp_path / "ui.sock", State(), setup=service)
    writer = Writer()
    await server.dispatch(writer, {"t": "runtime_status", "seq": 9, "id": "search"})
    assert writer.messages == [{"t": "error", "for": "runtime_status", "reason": "bad service"}]


async def test_setup_requests_after_hello_are_dispatched(service, tmp_path):
    server = IpcServer(tmp_path / "ui.sock", State(), setup=service, peer_uid=lambda _: os.getuid())
    reader = asyncio.StreamReader()
    reader.feed_data(b'{"t":"hello","v":1}\n{"t":"runtime_status"}\n')
    writer = Writer()
    task = asyncio.create_task(server._client(reader, writer))
    for _ in range(10):
        await asyncio.sleep(0)
    reader.feed_eof()
    await task
    assert [m["t"] for m in writer.messages] == ["state", "runtime_progress"]


async def test_picked_folder_secrets_are_in_progress(service):
    service._scan = SimpleNamespace(
        body={"candidates": []},
        roots={
            "/h/Documents": SimpleNamespace(
                candidate={"path": "/h/Documents", "left_out": [{"rule": "secrets", "files": 4}]}
            )
        },
    )
    result = await service.handle({"t": "index_start"})
    assert result["skipped"] == {"secrets": 4}


@pytest.mark.parametrize("layers,listed,vram", [("0", False, None), ("99", True, 0.9)])
async def test_progress_device_and_vram_from_index_server(
    service, monkeypatch, layers, listed, vram
):
    from omafindd import setup

    original_glob = Path.glob
    original_read_text = Path.read_text
    original_read_bytes = Path.read_bytes

    def glob(path, pattern):
        if str(path) == "/proc/987654/task":
            return iter([Path("/proc/987654/task/987654/children")])
        if str(path).startswith("/proc/"):
            return iter([])
        return original_glob(path, pattern)

    def text(path, *args, **kw):
        if str(path) == "/proc/987654/task/987654/children":
            return "987655"
        return original_read_text(path, *args, **kw)

    def data(path, *args, **kw):
        if str(path) == "/proc/987654/cmdline":
            return b"python\0bin/omafind\0"
        if str(path) == "/proc/987655/cmdline":
            return f"/runtime/llama-server\0-ngl\0{layers}\0".encode()
        return original_read_bytes(path, *args, **kw)

    monkeypatch.setattr(Path, "glob", glob)
    monkeypatch.setattr(Path, "read_text", text)
    monkeypatch.setattr(Path, "read_bytes", data)
    monkeypatch.setattr(
        setup.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout="987655, 922\n" if listed else ""),
    )
    result = await service.handle({"t": "index_start"})
    assert result["device"] == ("cpu" if layers == "0" else "gpu")
    assert result["vram_gb"] == vram


async def test_ipc_stop_cancels_requests_before_stopping_jobs(service, tmp_path):
    server = IpcServer(tmp_path / "ui.sock", State(), setup=service)
    cancelled = asyncio.Event()

    async def pending():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def stop():
        assert cancelled.is_set()

    service.stop = stop
    task = asyncio.create_task(pending())
    server._tasks.add(task)
    await asyncio.sleep(0)
    await server.stop()


async def test_discover_result_echoes_volume(service):
    assert (await service.handle({'t': 'discover_start', 'volume': 'usb'}))['volume'] == 'usb'


async def test_index_start_volume_spawns_volume_filter(service):
    await service.handle({'t': 'index_start', 'volume': 'usb'})
    assert service.test_calls[0][0][-2:] == ('--volume', 'usb')


async def test_drive_decision_reply(service):
    for choice in ('scan', 'ignore'):
        message = {'t': 'drive_decision', 'uuid': 'usb', 'choice': choice}
        assert await service.handle(message) == message
    assert 'usb' in service.ignored
    assert not service.test_calls


async def test_kick_defers_until_child_exit(service):
    await service.kick('u')
    assert service.busy
    await service.kick('usb')
    assert len(service.test_calls) == 1
    service.test_process.returncode = 0
    await service.poll(now=0)
    assert len(service.test_calls) == 2
    assert service.test_calls[-1][0][-2:] == ('--volume', 'usb')


async def test_kick_paused_or_unverified_does_not_spawn(service):
    service.model_ready = lambda: False
    await service.kick('u')
    assert not service.test_calls
    service.model_ready = lambda: True
    service.paused = lambda: True
    await service.kick('u')
    assert not service.test_calls
