import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from omafindd import discovery
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


COUNTS = {"text": 3, "pdf": 1, "image": 0, "video": 0, "audio": 0}
ZERO = dict.fromkeys(COUNTS, 0)


class FakeWalk:
    def __init__(self, root):
        self.root = root
        self.done = False
        self.stopped = False

    def run(self, emit, every=.25):
        emit({"root": str(self.root), "counts": {str(self.root / "Documents"): COUNTS},
              "done": False, "seconds": None})
        self.done = True
        emit({"root": str(self.root), "counts": {}, "done": True, "seconds": 0.4,
              "datasets": []})

    def snapshot(self):
        body = {"root": str(self.root), "counts": {str(self.root / "Documents"): COUNTS},
                "done": self.done, "seconds": 0.4 if self.done else None}
        if getattr(self, "error", None):
            body["error"] = self.error
        return body

    def count(self, path):
        if path == str(self.root / "Documents"):
            return COUNTS
        return ZERO if self.done else None

    def dataset(self, path):
        return None

    def stop(self):
        self.stopped = True


@pytest.fixture
async def service(tmp_path, monkeypatch):
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

    walks = []

    def top(*, home, volume=None):
        if volume is not None:
            return {"roots": [{"path": "/media/usb", "volume": volume}], "folders": []}
        return {"roots": [{"path": str(home), "volume": "u"}],
                "folders": [{"path": "/h/Documents", "name": "Documents", "xdg": True,
                             "repo": False, "hasChildren": True, "volume": "u"}]}

    def walk(root):
        walks.append(FakeWalk(root))
        return walks[-1]

    def children(path, walk):
        return {"path": path, "error": None,
                "dirs": [{"path": path + "/tax", "name": "tax", "repo": False,
                          "hasChildren": False, "counts": walk.count(path + "/tax"),
                          "rule": None, "evidence": None}]}


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
        top=top,
        walk=walk,
        children=children,
        estimate_device=lambda home: "gpu",
        volume_of=lambda path: ("u", Path("/h")),
        list_dirs=list_dirs,
        home=Path("/h"),
    )
    setup.test_calls, setup.test_pushes, setup.test_process = calls, pushes, process
    setup.test_walks = walks
    yield setup
    await asyncio.gather(*setup._discovery)


@pytest.mark.parametrize(
    "kind,method",
    [("runtime_status", "status"), ("runtime_install", "start"), ("runtime_pause", "pause")],
)
async def test_runtime_requests(service, kind, method):
    assert await service.handle({"t": kind}) == {"t": "runtime_progress"}
    assert service.runtime.calls == [method]


async def test_discover_start_replies_one_level_then_streams_counts(service):
    result = await service.handle({"t": "discover_start"})
    assert result == {
        "t": "discover_result", "volume": None, "home": "/h", "device": "gpu",
        "rates": discovery.RATES, "roots": [{"path": "/h", "volume": "u"}],
        "folders": [{"path": "/h/Documents", "name": "Documents", "xdg": True,
                     "repo": False, "hasChildren": True, "volume": "u"}]}
    await asyncio.gather(*service._discovery)
    assert service.test_pushes == [
        {"t": "discover_counts", "root": "/h", "counts": {},
         "done": False, "seconds": None, "reset": True},
        {"t": "discover_counts", "root": "/h", "counts": {"/h/Documents": COUNTS},
         "done": False, "seconds": None},
        {"t": "discover_counts", "root": "/h", "counts": {}, "done": True, "seconds": 0.4,
         "datasets": []}]


async def test_repeat_discover_start_reuses_walk_and_replays_counts(service):
    now = [0.0]
    service.clock = lambda: now[0]
    await service.handle({"t": "discover_start"})
    await asyncio.gather(*service._discovery)
    service.test_pushes.clear()
    await service.handle({"t": "discover_start"})
    await asyncio.gather(*service._discovery)
    assert len(service.test_walks) == 1
    assert service.test_pushes == [{"t": "discover_counts", **service.test_walks[0].snapshot()}]
    now[0] = service.WALK_TTL + 1
    await service.handle({"t": "discover_start"})
    await asyncio.gather(*service._discovery)
    assert len(service.test_walks) == 2


async def test_walk_failure_ends_with_done_and_error(service):
    attempts = []

    def broken(root):
        attempts.append(root)
        walk = FakeWalk(root)

        def run(emit, every=.25):
            raise OSError("fd failed: boom")

        walk.run = run
        return walk

    service.walk = broken
    await service.handle({"t": "discover_start"})
    await asyncio.gather(*service._discovery)
    assert service.test_pushes[-1] == {"t": "discover_counts", "root": "/h", "counts": {},
                                       "done": True, "seconds": None,
                                       "error": "fd failed: boom"}

    service.test_pushes.clear()
    await service.handle({"t": "discover_start"})
    await asyncio.gather(*service._discovery)
    assert service.test_pushes[-1]["done"]
    assert service.test_pushes[-1]["error"] == "fd failed: boom"
    assert attempts == [Path("/h"), Path("/h")]
    assert "/h" not in service._walked


async def test_discover_children_is_null_until_the_walk_reaches_it(service):
    await service.handle({"t": "discover_start"})
    before = await service.handle({"t": "discover_children", "path": "/h/Documents"})
    assert before["t"] == "discover_children" and before["path"] == "/h/Documents"
    assert before["volume"] == "u"
    assert before["dirs"][0]["counts"] is None
    await asyncio.gather(*service._discovery)
    after = await service.handle({"t": "discover_children", "path": "/h/Documents/"})
    assert after["dirs"][0]["counts"] == ZERO
    assert len(service.test_walks) == 1


async def test_discover_children_reuses_an_expired_walk(service):
    now = [0.0]
    service.clock = lambda: now[0]
    await service.handle({"t": "discover_start"})
    await asyncio.gather(*service._discovery)
    now[0] = service.WALK_TTL + 1
    service.test_pushes.clear()
    reply = await service.handle({"t": "discover_children", "path": "/h/Documents"})
    await asyncio.gather(*service._discovery)
    assert reply["dirs"][0]["counts"] == ZERO
    assert len(service.test_walks) == 1
    assert service.test_pushes == []


async def test_discover_children_outside_every_root_walks_that_folder(service):
    await service.handle({"t": "discover_start"})
    await service.handle({"t": "discover_children", "path": "/srv/archive"})
    assert [walk.root for walk in service.test_walks] == [Path("/h"), Path("/srv/archive")]


async def test_stop_stops_running_walks(service):
    await service.handle({"t": "discover_start"})
    await service.stop()
    assert service.test_walks[0].stopped


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

    service.top = failed
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
    result = await service.handle({"t": "index_start"})
    assert result["kinds"] == {
        "text": {"done": 0, "total": 1},
        "pdf": {"done": 2, "total": 2, "pages": 12},
        "image": {"done": 3, "total": 3, "ocr": 1},
        "video": {"done": 1, "total": 2},
        "audio": {"done": 0, "total": 0},
    }
    assert result["done"] == 6 and result["queued"] == 2
    assert result["skipped"] == {"size-cap": 2}
    assert result["failed"] == {"encrypted-pdf": 1}
    assert result["problems"] == [{"path": "/h/e.pdf", "reason": "encrypted-pdf"}]
    assert result["volume"] == "u"
    assert result["volumes"] == {"u": {"label": "root", "done": 6, "total": 8}}


@pytest.mark.parametrize(
    "message",
    [{"t": "discover_children"}, {"t": "discover_children", "path": "relative/x"},
     {"t": "fs_list", "path": 2}, {"t": "discover_start", "volume": []}],
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
    async def broken(message, **kwargs):
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


async def test_index_progress_reads_stores_and_spawns_nothing(service):
    result = await service.handle({"t": "index_progress"})
    assert result["t"] == "progress" and result["running"] is False
    assert result["done"] == 0 and result["queued"] == 0
    assert service.test_calls == []


async def test_discover_stop_keeps_other_clients_walk(service):
    one, two = object(), object()
    await service.handle({'t': 'discover_start'}, client=one)
    await service.handle({'t': 'discover_start'}, client=two)
    assert len(service.test_walks) == 1
    assert await service.handle({'t': 'discover_stop'}, client=one) == {'t': 'discover_stop'}
    assert not service.test_walks[0].stopped
    await service.disconnect(two)
    assert service.test_walks[0].stopped


async def test_repeat_start_during_a_walk_replays_without_another_walk(service):
    await service.handle({'t': 'discover_start'})
    await service.handle({'t': 'discover_start'})
    await asyncio.gather(*service._discovery)
    assert len(service.test_walks) == 1
    assert sum(message['done'] for message in service.test_pushes) >= 1


async def test_stop_during_initial_read_does_not_start_a_walk(service, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def gated(fn, *args, **kwargs):
        if fn is service.top:
            entered.set()
            await release.wait()
        return fn(*args, **kwargs)

    monkeypatch.setattr(asyncio, 'to_thread', gated)
    pending = asyncio.create_task(service.handle({'t': 'discover_start'}, client='picker'))
    await entered.wait()
    await service.handle({'t': 'discover_stop'}, client='picker')
    release.set()
    await pending
    await asyncio.gather(*service._discovery)
    assert not service.test_walks


async def test_a_fresh_walk_begins_with_a_cache_reset(service):
    await service.handle({'t': 'discover_start'})
    await asyncio.gather(*service._discovery)
    assert service.test_pushes[0] == {'t': 'discover_counts', 'root': '/h', 'counts': {},
                                     'done': False, 'seconds': None, 'reset': True}


async def test_root_walks_run_one_worker_at_a_time(service, monkeypatch):
    release, entered = asyncio.Event(), asyncio.Event()
    active = peak = 0
    service.top = lambda **kwargs: {'roots': [{'path': '/h'}, {'path': '/m'}], 'folders': []}

    async def controlled(fn, *args, **kwargs):
        nonlocal active, peak
        if fn.__name__ == 'run':
            active += 1
            peak = max(peak, active)
            entered.set()
            await release.wait()
            try:
                return fn(*args, **kwargs)
            finally:
                active -= 1
        return fn(*args, **kwargs)

    monkeypatch.setattr(asyncio, 'to_thread', controlled)
    await service.handle({'t': 'discover_start'})
    await entered.wait()
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(*service._discovery)
    assert peak == 1
    assert len(service.test_walks) == 2



async def test_children_reuse_deepest_known_root_volume(service):
    await service.handle({"t": "discover_start"})
    await service.handle({"t": "discover_start", "volume": "usb"})
    service.volume_of = lambda path: pytest.fail("expanding a known root probes findmnt")
    home = await service.handle({"t": "discover_children", "path": "/h/Documents"})
    drive = await service.handle({"t": "discover_children", "path": "/media/usb/Photos"})
    assert home["volume"] == "u"
    assert drive["volume"] == "usb"


@pytest.mark.parametrize("path", ["/", "/proc", "/sys/", "/dev", "/run", "/proc/self"])
async def test_children_refuse_filesystem_and_pseudo_roots(service, path):
    reply = await service.handle({"t": "discover_children", "path": path})
    assert reply["t"] == "error" and reply["code"] == "bad-request"
    assert not service.test_walks


async def test_count_broadcast_failure_still_finishes_the_walk(service):
    pushes = []

    async def broadcast(body):
        if body["counts"]:
            raise UnicodeEncodeError("utf-8", "\udcff", 0, 1, "surrogate")
        pushes.append(body)

    service.broadcast = broadcast
    await service.handle({"t": "discover_start"})
    await asyncio.gather(*service._discovery)
    assert pushes[-1]["done"] is True and pushes[-1]["error"]
    assert service.test_walks[0].done and service.test_walks[0].error
    assert "/h" not in service._walked


async def test_children_reuse_a_known_removable_mount_under_run(service):
    service.top = lambda **kwargs: {
        'roots': [{'path': '/run/media/u/USB', 'volume': 'usb'}], 'folders': []}
    await service.handle({'t': 'discover_start'})
    service.volume_of = lambda path: pytest.fail('known removable mount was probed again')
    reply = await service.handle({'t': 'discover_children', 'path': '/run/media/u/USB/Photos'})
    assert reply['volume'] == 'usb'
    assert [walk.root for walk in service.test_walks] == [Path('/run/media/u/USB')]


async def test_children_prefer_the_deepest_known_root(service):
    service.top = lambda **kwargs: {
        'roots': [{'path': '/h', 'volume': 'home'}, {'path': '/h/USB', 'volume': 'usb'}],
        'folders': []}
    await service.handle({'t': 'discover_start'})
    service.volume_of = lambda path: pytest.fail('known root was probed again')
    reply = await service.handle({'t': 'discover_children', 'path': '/h/USB/Photos'})
    assert reply['volume'] == 'usb'
    assert len(service.test_walks) == 2


async def test_initial_count_broadcast_failure_finishes_without_starting_a_worker(service):
    pushes = []

    async def broadcast(body):
        if not body['done']:
            raise ValueError('Cannot send counts')
        pushes.append(body)

    service.broadcast = broadcast
    await service.handle({'t': 'discover_start'})
    await asyncio.gather(*service._discovery)
    assert pushes == [{'t': 'discover_counts', 'root': '/h', 'counts': {}, 'done': True,
                       'seconds': None, 'error': 'Cannot send counts'}]
    assert service.test_walks[0].done and service.test_walks[0].stopped
    assert '/h' not in service._walked


async def test_binds_get_returns_live_binds(service):
    import subprocess

    calls = []

    def run(argv, **kw):
        calls.append((argv, kw))
        return subprocess.CompletedProcess(
            argv, 0, json.dumps([{"modmask": 64, "key": "D", "description": "Files"}]), "")

    service.run = run
    assert await service.handle({"t": "binds_get"}) == {
        "t": "binds", "binds": [{"chord": "Super D", "description": "Files"}]}
    assert calls[0][0] == ["hyprctl", "binds", "-j"] and calls[0][1]["timeout"] == 5


async def test_binds_get_failure_names_the_request(service):
    def run(argv, **kw):
        raise FileNotFoundError("hyprctl")

    service.run = run
    reply = await service.handle({"t": "binds_get"})
    assert reply["t"] == "error" and reply["for"] == "binds_get"
    assert reply["code"] == "binds-failed"
    assert reply["reason"].startswith("Could not read your Hyprland bindings")


@pytest.mark.parametrize("output,code", [("", 1), ("not JSON", 0), ("[broken", 0),
                                       ('[{"key":"E"}]', 0)])
async def test_binds_get_rejects_failed_or_malformed_output(service, output, code):
    import subprocess

    service.run = lambda argv, **kw: subprocess.CompletedProcess(argv, code, output, "failed")
    reply = await service.handle({"t": "binds_get"})
    assert reply["t"] == "error" and reply["code"] == "binds-failed"
    assert reply["reason"].startswith("Could not read your Hyprland bindings")


@pytest.mark.parametrize("error", [
    FileNotFoundError(2, "No such file or directory", "hyprctl"),
    OSError("Cannot read bindings."),
])
async def test_binds_get_failure_has_one_clean_sentence(service, error):
    def run(argv, **kw):
        raise error

    service.run = run
    reply = await service.handle({"t": "binds_get"})
    assert reply["reason"] == "Could not read your Hyprland bindings."
