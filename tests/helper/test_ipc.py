import asyncio
import json
import os
import socket
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from omafindd import paths
from omafindd.ipc import AlreadyRunning, IpcServer
from omafindd.main import _serve
from omafindd.state import State

HELLO = b'{"t":"hello","v":1}\n'
INITIAL = {"t": "state", "v": 1, "runtime": "missing", "model": "missing",
           "embedder": "stopped"}


@pytest.fixture
def runtime(monkeypatch):
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        root = Path(directory)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(root))
        monkeypatch.setenv("HOME", str(root / "home"))
        monkeypatch.setenv("XDG_DATA_HOME", str(root / "data"))
        yield root


@pytest.fixture
async def server(runtime):
    instance = IpcServer(paths.socket_path())
    await instance.start()
    try:
        yield instance
    finally:
        await instance.stop()


@asynccontextmanager
async def connect(server):
    reader, writer = await asyncio.open_unix_connection(server.path)
    try:
        yield reader, writer
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (BrokenPipeError, ConnectionResetError):
            pass


async def reply(reader):
    return json.loads(await asyncio.wait_for(reader.readline(), 1))


async def test_socket_and_directory_are_private(server):
    assert server.path.parent.stat().st_mode & 0o777 == 0o700
    assert server.path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("writes,answers", [
    ([HELLO], 1), ([HELLO + HELLO], 2), ([HELLO[:10], HELLO[10:]], 1),
])
async def test_hello_handles_line_framing(server, writes, answers):
    async with connect(server) as (reader, writer):
        for part in writes:
            writer.write(part)
            await writer.drain()
            await asyncio.sleep(0.01)
        for _ in range(answers):
            assert await reply(reader) == INITIAL


@pytest.mark.parametrize("bad", [b"not json\n", b"[]\n", b"null\n", b"\xff\n"])
async def test_bad_json_is_skipped(server, bad):
    async with connect(server) as (reader, writer):
        writer.write(bad + HELLO)
        await writer.drain()
        assert await reply(reader) == INITIAL


@pytest.mark.parametrize("version", [2, True, "1", None])
async def test_wrong_protocol_version_closes_connection(server, version):
    async with connect(server) as (reader, writer):
        writer.write(json.dumps({"t": "hello", "v": version}).encode() + b"\n")
        await writer.drain()
        assert await asyncio.wait_for(reader.read(), 1) == b""


async def test_oversized_line_closes_connection(server):
    async with connect(server) as (reader, writer):
        writer.write(b"x" * (2 * 1024 * 1024) + b"\n")
        try:
            await writer.drain()
            assert await asyncio.wait_for(reader.read(), 1) == b""
        except (BrokenPipeError, ConnectionResetError):
            pass


async def test_foreign_uid_is_closed(runtime):
    server = IpcServer(paths.socket_path(), peer_uid=lambda sock: os.getuid() + 1)
    await server.start()
    try:
        async with connect(server) as (reader, _writer):
            assert await asyncio.wait_for(reader.read(), 1) == b""
    finally:
        await server.stop()


async def test_stale_socket_is_replaced_and_directory_is_secured(runtime):
    path = paths.socket_path()
    path.parent.mkdir(mode=0o755)
    with socket.socket(socket.AF_UNIX) as stale:
        stale.bind(str(path))
    instance = IpcServer(path)
    await instance.start()
    try:
        assert path.parent.stat().st_mode & 0o777 == 0o700
        async with connect(instance) as (reader, writer):
            writer.write(HELLO)
            await writer.drain()
            assert await reply(reader) == INITIAL
    finally:
        await instance.stop()


async def test_live_server_raises_already_running_without_removing_socket(server):
    second = IpcServer(server.path)
    with pytest.raises(AlreadyRunning):
        await second.start()
    await second.stop()
    async with connect(server) as (reader, writer):
        writer.write(HELLO)
        await writer.drain()
        assert await reply(reader) == INITIAL


async def test_non_socket_path_is_preserved(runtime):
    path = paths.socket_path()
    path.parent.mkdir()
    path.write_text("Keep this file")
    with pytest.raises(FileExistsError):
        await IpcServer(path).start()
    assert path.read_text() == "Keep this file"


async def test_state_pushes_changes_to_every_client_only_on_change(server):
    async with connect(server) as (first, writer1), connect(server) as (second, writer2):
        for writer, reader in ((writer1, first), (writer2, second)):
            writer.write(HELLO)
            await writer.drain()
            assert await reply(reader) == INITIAL
        await server.state.update(runtime="ready", embedder="text")
        changed = {**INITIAL, "runtime": "ready", "embedder": "text"}
        assert await reply(first) == changed
        assert await reply(second) == changed
        await server.state.update(runtime="ready", embedder="text")
        await server.state.update(model="ready", embedder="full")
        changed.update(model="ready", embedder="full")
        assert await reply(first) == changed
        assert await reply(second) == changed
        for reader in (first, second):
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(reader.readline(), 0.02)


async def test_stop_closes_clients_and_removes_socket(server):
    async with connect(server) as (reader, writer):
        writer.write(HELLO)
        await writer.drain()
        assert await reply(reader) == INITIAL
        await server.stop()
        assert not server.path.exists()
        assert await asyncio.wait_for(reader.read(), 1) == b""


async def test_one_mib_line_is_accepted(server):
    async with connect(server) as (reader, writer):
        writer.write(HELLO[:-1] + b" " * (1024 * 1024 - len(HELLO) + 1) + b"\n")
        await writer.drain()
        assert await reply(reader) == INITIAL


def test_executable_directory_is_not_a_runtime(runtime):
    paths.runtime_bin().mkdir(parents=True)
    assert State.detect().message() == INITIAL


def test_state_detection_does_not_create_data_directory(runtime):
    directory = runtime / 'data/omafind'
    assert State.detect().message() == INITIAL
    assert State.detect().message() == INITIAL
    assert not directory.exists()


def test_state_detection_does_not_change_data_permissions(runtime):
    directory = paths.data_dir()
    directory.chmod(0o755)
    assert State.detect().message() == INITIAL
    assert State.detect().message() == INITIAL
    assert directory.stat().st_mode & 0o777 == 0o755


@pytest.mark.parametrize("executable,files,want_runtime,want_model", [
    (False, [], "missing", "missing"),
    (True, ["embeddinggemma-2-Q8_0.gguf"], "ready", "missing"),
    (False, ["embeddinggemma-2-Q8_0.gguf", "mmproj-embeddinggemma-2-Q8_0.gguf"],
     "missing", "ready"),
    (True, ["embeddinggemma-2-Q8_0.gguf", "mmproj-embeddinggemma-2-Q8_0.gguf"],
     "ready", "ready"),
])
def test_state_detects_executable_and_both_models(runtime, executable, files,
                                                want_runtime, want_model):
    binary = paths.runtime_bin()
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o700 if executable else 0o600)
    paths.model_dir().mkdir()
    for name in files:
        (paths.model_dir() / name).touch()
    assert State.detect().message() == {
        **INITIAL, "runtime": want_runtime, "model": want_model,
    }


async def wait_for_socket(path):
    async with asyncio.timeout(2):
        while not path.exists():
            await asyncio.sleep(0.01)


async def test_daemon_exits_zero_when_manifest_disappears(runtime):
    manifest = runtime / "manifest.json"
    manifest.write_text("{}")
    task = asyncio.create_task(_serve(manifest, interval=0.01))
    try:
        await wait_for_socket(paths.socket_path())
        reader, writer = await asyncio.open_unix_connection(paths.socket_path())
        writer.write(HELLO)
        await writer.drain()
        assert await reply(reader) == INITIAL
        manifest.unlink()
        assert await asyncio.wait_for(task, 1) == 0
        assert await asyncio.wait_for(reader.read(), 1) == b""
        writer.close()
        await writer.wait_closed()
        assert not paths.socket_path().exists()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_daemon_updates_readiness_after_install(runtime):
    manifest = runtime / "manifest.json"
    manifest.touch()
    task = asyncio.create_task(_serve(manifest, interval=0.01))
    try:
        await wait_for_socket(paths.socket_path())
        reader, writer = await asyncio.open_unix_connection(paths.socket_path())
        writer.write(HELLO)
        await writer.drain()
        assert await reply(reader) == INITIAL
        binary = paths.runtime_bin()
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o700)
        paths.model_dir().mkdir()
        for name in ("embeddinggemma-2-Q8_0.gguf", "mmproj-embeddinggemma-2-Q8_0.gguf"):
            (paths.model_dir() / name).touch()
        assert await reply(reader) == {**INITIAL, "runtime": "ready", "model": "ready"}
        writer.close()
        await writer.wait_closed()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_python_module_exits_zero_for_missing_manifest(runtime):
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "omafindd", stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 2)
        assert process.returncode == 0, (stdout, stderr)
        assert not paths.socket_path().exists()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


class MemoryWriter:
    def __init__(self):
        self.lines = asyncio.Queue()
        self.closed = asyncio.Event()

    def get_extra_info(self, name):
        assert name == "socket"
        return self

    def write(self, data):
        self.lines.put_nowait(data)

    async def drain(self):
        pass

    def close(self):
        self.closed.set()

    async def wait_closed(self):
        await self.closed.wait()


@pytest.fixture
async def memory_server(tmp_path):
    instance = IpcServer(tmp_path / "ui.sock", State(), peer_uid=lambda sock: os.getuid())
    try:
        yield instance
    finally:
        await instance.stop()


def memory_client(server):
    reader = asyncio.StreamReader(limit=1_048_577)
    writer = MemoryWriter()
    server._accept(reader, writer)
    return reader, writer


async def memory_reply(writer):
    return json.loads(await asyncio.wait_for(writer.lines.get(), 1))


@pytest.mark.parametrize("writes,answers", [
    ([HELLO], 1), ([HELLO + HELLO], 2), ([HELLO[:10], HELLO[10:]], 1),
])
async def test_memory_transport_handles_line_framing(memory_server, writes, answers):
    reader, writer = memory_client(memory_server)
    for part in writes:
        reader.feed_data(part)
        await asyncio.sleep(0)
    for _ in range(answers):
        assert await memory_reply(writer) == INITIAL
    assert writer.lines.empty()


@pytest.mark.parametrize("bad", [b"not json\n", b"[]\n", b"null\n", b"\xff\n"])
async def test_memory_transport_skips_bad_json(memory_server, bad):
    reader, writer = memory_client(memory_server)
    reader.feed_data(bad + HELLO)
    assert await memory_reply(writer) == INITIAL


@pytest.mark.parametrize("message", [
    {"t": "hello", "v": 2}, {"t": "hello", "v": True}, {"t": "hello", "v": "1"},
    {"t": "hello", "v": None}, {"t": "hello"}, {"t": "future", "v": 2},
])
async def test_memory_transport_closes_wrong_version(memory_server, message):
    reader, writer = memory_client(memory_server)
    reader.feed_data(json.dumps(message).encode() + b"\n")
    await asyncio.wait_for(writer.closed.wait(), 1)
    assert writer.lines.empty()


@pytest.mark.parametrize("size,accepted", [(1_048_576, True), (2_097_152, False)])
async def test_memory_transport_enforces_line_limit(memory_server, size, accepted):
    reader, writer = memory_client(memory_server)
    reader.feed_data(HELLO[:-1] + b" " * (size - len(HELLO) + 1) + b"\n")
    if accepted:
        assert await memory_reply(writer) == INITIAL
    else:
        await asyncio.wait_for(writer.closed.wait(), 1)
        assert writer.lines.empty()


async def test_memory_transport_rejects_foreign_uid(memory_server):
    memory_server.peer_uid = lambda sock: os.getuid() + 1
    reader, writer = memory_client(memory_server)
    reader.feed_data(HELLO)
    await asyncio.wait_for(writer.closed.wait(), 1)
    assert writer.lines.empty()


async def test_memory_transport_broadcasts_only_state_changes(memory_server):
    clients = [memory_client(memory_server) for _ in range(2)]
    for reader, writer in clients:
        reader.feed_data(HELLO)
        assert await memory_reply(writer) == INITIAL
    await memory_server.state.update(runtime="ready", embedder="text")
    for _, writer in clients:
        assert await memory_reply(writer) == {**INITIAL, "runtime": "ready", "embedder": "text"}
    await memory_server.state.update(runtime="ready", embedder="text")
    for _, writer in clients:
        assert writer.lines.empty()
    await memory_server.stop()
    for _, writer in clients:
        assert writer.closed.is_set()


@pytest.mark.parametrize("remove_manifest", [True, False])
async def test_daemon_polls_and_stops_with_fake_socket(runtime, monkeypatch, remove_manifest):
    from omafindd import main

    started = asyncio.Event()
    stopped = asyncio.Event()
    published = asyncio.Queue()

    class FakeServer:
        def __init__(self, path):
            assert paths.data_dir_path().stat().st_mode & 0o777 == 0o700
            self.state = State.detect()
            self.state.on_change = self.broadcast

        async def start(self):
            started.set()

        async def stop(self):
            stopped.set()

        async def broadcast(self, message):
            published.put_nowait(message)

    monkeypatch.setattr(main, "IpcServer", FakeServer)
    manifest = runtime / "manifest.json"
    manifest.touch()
    task = asyncio.create_task(_serve(manifest, interval=0.01))
    try:
        await asyncio.wait_for(started.wait(), 1)
        binary = paths.runtime_bin()
        binary.parent.mkdir(parents=True)
        binary.touch(mode=0o700)
        paths.model_dir().mkdir()
        for name in ("embeddinggemma-2-Q8_0.gguf", "mmproj-embeddinggemma-2-Q8_0.gguf"):
            (paths.model_dir() / name).touch()
        assert await asyncio.wait_for(published.get(), 1) == {
            **INITIAL, "runtime": "ready", "model": "ready",
        }
        if remove_manifest:
            manifest.unlink()
            assert await asyncio.wait_for(task, 1) == 0
        else:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert stopped.is_set()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
