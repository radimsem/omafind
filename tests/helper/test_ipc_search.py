import asyncio
import json
import os
import sqlite3
from pathlib import Path

import pytest
from fakes.embedder import FakeEmbedder
from omafindd import errors
from omafindd.crawler import crawl
from omafindd.extractors import Segment
from omafindd.ipc import IpcServer
from omafindd.search import Searcher
from omafindd.settings import Settings
from omafindd.state import State
from omafindd.store import Store

pytest_plugins = ("test_cli",)

ITEM_KEYS = {
    "id",
    "kind",
    "path",
    "name",
    "dir",
    "volume",
    "label",
    "drive",
    "offline",
    "loc",
    "loc_end",
    "leg",
    "part",
    "z",
    "score",
    "weak",
    "hits",
    "snippet",
    "thumb",
    "mtime",
    "size",
    "info",
}


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "index/v.sqlite", volume="v", mount=tmp_path)
    yield value
    value.close()


async def seeded_search(store, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("lunar eclipse telescope")
    crawl(store, [{"path": str(tmp_path), "excludes": []}])
    file = store.db.execute("SELECT id FROM files").fetchone()[0]
    vectors = await FakeEmbedder().embed_documents(["lunar eclipse telescope"])
    store.write(
        file,
        [Segment("chunk", "text", "lunar eclipse telescope", loc=41, loc_end=42)],
        vectors,
        state="done",
        info={},
    )
    return Searcher([store], FakeEmbedder())


async def test_item_shape_and_same_seq_later_reply(store, tmp_path):
    from omafindd.service import SearchService

    searcher = await seeded_search(store, tmp_path)
    service = SearchService(
        store.path.parent,
        lambda: Settings(),
        FakeEmbedder(),
        State(model="ready"),
        volume_resolver=lambda path, **kwargs: ("v", tmp_path),
    )
    service.searcher = searcher
    first = await service.handle({"t": "search", "seq": 7, "q": "lunar", "legs": ["words"]})
    second = await service.handle(
        {"t": "search", "seq": 7, "q": "lunar", "legs": ["words", "meaning"], "limit": 40}
    )
    assert first["seq"] == second["seq"] == 7
    assert second["legs"] == ["words", "meaning"]
    assert set(second["items"][0]) == ITEM_KEYS
    assert second["items"][0]["offline"] is False
    assert first["items"][0]["loc"] == 41
    await service.stop()


async def test_warm_failed_reports_the_error(tmp_path):
    from omafindd.embedder import EmbeddingError
    from omafindd.service import SearchService

    class Failed(FakeEmbedder):
        async def start(self, mode):
            raise EmbeddingError("Vulkan device lost")

    service = SearchService(tmp_path, lambda: Settings(), Failed(), State())
    reply = await service.handle({"t": "warm"})
    assert reply == {"t": "warm_failed",
                     "error": errors.embedding_unavailable("Vulkan device lost").to_dict()}
    await service.stop()


async def test_start_failure_keeps_its_error_object(store, tmp_path):
    from omafindd.embedder import EmbeddingError
    from omafindd.service import SearchService

    await seeded_search(store, tmp_path)
    failure = errors.server_start_failed("it exited with code 1", tmp_path / "llama-server.log")

    class Failed(FakeEmbedder):
        async def start(self, mode):
            raise EmbeddingError("Embedding server failed to start", user_error=failure)

    service = SearchService(
        store.path.parent, lambda: Settings(), Failed(), State(model="ready"),
        volume_resolver=lambda path, **kwargs: ("v", tmp_path), mounts_resolver=lambda: {}
    )
    try:
        assert await service.handle({"t": "warm"}) == {"t": "warm_failed",
                                                       "error": failure.to_dict()}
        reply = await service.handle({"t": "search", "seq": 1, "q": "lunar"})
        assert reply["degraded"] == failure.to_dict()
        assert reply["items"][0]["name"] == "notes.txt"
    finally:
        await service.stop()


async def test_warm_server_stops_after_idle_timeout(tmp_path):
    from omafindd.service import SearchService

    embedder = FakeEmbedder()
    state = State()
    service = SearchService(tmp_path, lambda: Settings(warm_minutes=0), embedder, state)
    assert (await service.handle({"t": "warm"}))["embedder"] == "text"
    await asyncio.sleep(0.01)
    assert embedder.mode is None
    assert state.embedder == "stopped"
    await service.stop()


async def test_daemon_sees_db_added_by_cli(tmp_path):
    from omafindd.service import SearchService

    service = SearchService(
        tmp_path / "index",
        lambda: Settings(),
        FakeEmbedder(),
        State(),
        volume_resolver=lambda path, **kwargs: ("v", tmp_path),
    )
    first = await service.handle({"t": "search", "seq": 1, "q": "lunar"})
    assert first == {"t": "error", "seq": 1, **errors.no_index().to_dict()}
    store = Store(tmp_path / "index/v.sqlite", volume="v", mount=tmp_path)
    await seeded_search(store, tmp_path)
    second = await service.handle({"t": "search", "seq": 2, "q": "lunar"})
    assert second["items"][0]["name"] == "notes.txt"
    await service.stop()
    store.close()


@pytest.mark.parametrize("stage", ["empty", "schema", "uuid"])
async def test_search_skips_incomplete_database_and_retries_next_search(tmp_path, stage):
    from omafindd.service import SearchService
    from omafindd.store import SCHEMA

    directory = tmp_path / "index"
    directory.mkdir()
    path = directory / "v.sqlite"
    with sqlite3.connect(path) as db:
        if stage != "empty":
            db.executescript(SCHEMA)
        if stage == "uuid":
            db.execute("INSERT INTO meta VALUES('volume_uuid','v')")
    db.close()
    service = SearchService(
        directory, lambda: Settings(), FakeEmbedder(), State(),
        volume_resolver=lambda path, **kwargs: ("v", tmp_path), mounts_resolver=lambda: {}
    )
    store = None
    try:
        reply = await service.handle(
            {"t": "search", "seq": 1, "q": "lunar", "legs": ["words"]}
        )
        assert reply["code"] == "no-index"
        assert path not in service._mount_files
        assert service.searcher.stores == []
        store = Store(path, volume="v", mount=tmp_path)
        await seeded_search(store, tmp_path)
        reply = await service.handle(
            {"t": "search", "seq": 2, "q": "lunar", "legs": ["words"]}
        )
        assert reply["items"][0]["name"] == "notes.txt"
        assert path in service._mount_files
    finally:
        await service.stop()
        if store is not None:
            store.close()


async def test_search_caches_mounts_until_mountinfo_or_database_set_changes(tmp_path, monkeypatch):
    import subprocess
    from functools import partial

    from omafindd.service import SearchService
    from omafindd.store import mounted_volumes, volume_for

    store = Store(tmp_path / "index/v.sqlite", volume="v", mount=tmp_path)
    await seeded_search(store, tmp_path)
    store.close()
    calls = []
    snapshot = b"first mount table"
    read = Path.read_bytes

    def mountinfo(path):
        return snapshot if path == Path("/proc/self/mountinfo") else read(path)

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, f"v {tmp_path}\n", "")

    monkeypatch.setattr(Path, "read_bytes", mountinfo)
    service = SearchService(
        tmp_path / "index", lambda: Settings(roots=[{"path": str(tmp_path)}]),
        FakeEmbedder(), State(), volume_resolver=partial(volume_for, run=run),
        mounts_resolver=lambda: mounted_volumes(run=run)
    )
    query = {"t": "search", "seq": 1, "q": "lunar", "legs": ["words"]}
    try:
        assert (await service.handle(query))["items"][0]["name"] == "notes.txt"
        assert len(calls) == 4, "volume_for rebuilt the mounts map for each path"
        calls.clear()
        for _ in range(3):
            assert (await service.handle(query))["items"][0]["name"] == "notes.txt"
        assert calls == [], "unchanged mount table was rediscovered per query"
        snapshot = b"second mount table"
        await service.handle(query)
        assert len(calls) == 4
        calls.clear()
        extra = Store(tmp_path / "index/extra.sqlite", volume="extra", mount=tmp_path)
        extra.close()
        await service.handle(query)
        assert len(calls) == 4
        calls.clear()
        await service.handle(query)
        assert calls == []
    finally:
        await service.stop()


async def test_socket_dispatch_stores_connection_latest_items(store, tmp_path):
    from omafindd.service import SearchService

    await seeded_search(store, tmp_path)
    service = SearchService(
        store.path.parent,
        lambda: Settings(),
        FakeEmbedder(),
        State(),
        volume_resolver=lambda path, **kwargs: ("v", tmp_path),
    )
    server = IpcServer(tmp_path / "ui.sock", State(), service=service)

    class Writer:
        def __init__(self):
            self.data = bytearray()

        def write(self, data):
            self.data.extend(data)

        async def drain(self):
            pass

    writer = Writer()
    await server.dispatch(writer, {"t": "search", "seq": 7, "q": "lunar", "legs": ["words"]})
    reply = json.loads(writer.data)
    assert server.resolve(writer, reply["items"][0]["id"])["loc"] == 41
    assert server.resolve(Writer(), reply["items"][0]["id"]) is None
    await service.stop()


@pytest.mark.parametrize(
    "response,code",
    [
        ({"t": "results", "seq": 1, "items": []}, 0),
        ({"t": "error", "seq": 1, **errors.no_index().to_dict()}, 1),
        (False, 3),
    ],
)
def test_cli_search_exit_codes(cli, env, capsys, response, code):
    assert (
        cli.main(["search", "--json", "lunar"], env, request=lambda *args, **kwargs: response)
        == code
    )
    output = capsys.readouterr()
    if code == 0:
        assert json.loads(output.out) == response
    elif code == 1:
        assert output.err == "Nothing is indexed yet. Open setup and start the first index.\n"


@pytest.mark.parametrize(
    "args",
    [
        ["search"],
        ["search", "--json", "--limit", "0", "x"],
        ["search", "--limit", "bad", "x"],
        ["reindex", "--bad"],
    ],
)
def test_cli_bad_search_arguments_exit_2(cli, env, args):
    assert cli.main(args, env) == 2


def test_cli_reindex_without_roots_names_setting_and_flag(cli, env, capsys):
    assert cli.main(["reindex"], env) == 2
    assert "--root" in capsys.readouterr().err


async def test_cli_reindex_offline_takes_lock_and_drains(cli, env, tmp_path):
    from omafindd.indexing import reindex

    root = tmp_path / "corpus"
    root.mkdir()
    (root / "a.txt").write_text("lunar eclipse")
    directory = Path(env["XDG_DATA_HOME"]) / "omafind"
    await reindex(
        [{"path": str(root), "excludes": []}],
        directory=directory,
        embedder=FakeEmbedder(),
        volume_resolver=lambda path, **kwargs: ("v", tmp_path),
    )
    index = Store(directory / "index/v.sqlite", volume="v", mount=tmp_path)
    assert index.db.execute("SELECT state FROM files").fetchone()[0] == "done"
    assert (directory / "index.lock").stat().st_mode & 0o777 == 0o600
    assert (directory / "journal").read_text() == ""
    index.close()


async def test_words_query_stops_warm_server_with_zero_idle_timeout(store, tmp_path):
    from omafindd.service import SearchService

    await seeded_search(store, tmp_path)
    embedder = FakeEmbedder()
    service = SearchService(
        store.path.parent,
        lambda: Settings(warm_minutes=0),
        embedder,
        State(),
        volume_resolver=lambda path, **kwargs: ("v", tmp_path),
    )
    await service.handle({"t": "warm"})
    await service.handle({"t": "search", "seq": 1, "q": "lunar", "legs": ["words"]})
    await asyncio.sleep(0.01)
    assert embedder.mode is None
    await service.stop()


async def test_cli_only_external_volume_is_discovered(tmp_path):
    from omafindd.service import SearchService

    external = tmp_path / "external"
    external.mkdir()
    directory = tmp_path / "data/index"
    store = Store(directory / "external.sqlite", volume="external", mount=external)
    await seeded_search(store, external)
    service = SearchService(
        directory,
        lambda: Settings(),
        FakeEmbedder(),
        State(),
        volume_resolver=lambda path, **kwargs: ("internal", tmp_path),
        mounts_resolver=lambda: {"external": external},
    )
    reply = await service.handle({"t": "search", "seq": 1, "q": "lunar", "legs": ["words"]})
    assert reply["items"][0]["path"] == str(external / "notes.txt")
    await service.stop()
    store.close()


def test_reindex_help_needs_only_stdlib(cli):
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-S", str(cli.PLUGIN_ROOT / "bin/omafind"), "reindex", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "--root" in result.stdout


def test_reindex_replaces_process_with_installed_interpreter(cli, env, tmp_path):
    python = Path(env["HOME"]) / ".local/share/omafind/venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("fixture")
    calls = []

    def execve(path, argv, environment):
        calls.append((path, argv, environment))
        raise SystemExit(17)

    (tmp_path / "corpus").mkdir()
    root = str(tmp_path / "corpus")
    with pytest.raises(SystemExit, match="17"):
        cli.main(["reindex", "--root", root, "--volume", "v"], env, execve=execve)
    assert calls == [(str(python), [str(python), str(cli.PLUGIN_ROOT / "bin/omafind"),
                                  "reindex", "--root", root, "--volume", "v"], env)]


async def test_reindex_moved_file_keeps_segments_without_embedding(tmp_path):
    from omafindd.indexing import reindex

    root = tmp_path / "corpus"
    root.mkdir()
    source = root / "a.txt"
    source.write_text("lunar eclipse")
    directory = tmp_path / "data"
    roots = [{"path": str(root)}]
    await reindex(roots, directory=directory, embedder=FakeEmbedder(),
                  volume_resolver=lambda path, **kwargs: ("v", tmp_path))
    store = Store(directory / "index/v.sqlite", volume="v", mount=tmp_path)
    before = list(map(tuple, store.db.execute("SELECT * FROM segments")))
    source.rename(root / "b.txt")

    class Observe(FakeEmbedder):
        calls = 0

        async def embed_documents(self, parts):
            self.calls += 1
            return await super().embed_documents(parts)

    embedder = Observe()
    try:
        await reindex(roots, directory=directory, embedder=embedder,
                      volume_resolver=lambda path, **kwargs: ("v", tmp_path))
        assert embedder.calls == 0
        assert store.db.execute("SELECT path,state FROM files").fetchone()[:] == (
            "corpus/b.txt", "done"
        )
        assert list(map(tuple, store.db.execute("SELECT * FROM segments"))) == before
    finally:
        store.close()


async def test_indexer_and_service_share_home_mount_with_roots_on_both_mounts(
    tmp_path, monkeypatch
):
    import subprocess
    from functools import partial

    from omafindd.indexing import reindex
    from omafindd.service import SearchService
    from omafindd.store import mounted_volumes, volume_for

    home = tmp_path / "home/u"
    outside = tmp_path / "opt"
    home.mkdir(parents=True)
    outside.mkdir()
    (home / "inside.txt").write_text("lunar eclipse")
    (outside / "outside.txt").write_text("lunar eclipse")
    monkeypatch.setattr(Path, "home", lambda: home)

    def run(argv, **kwargs):
        if "-T" not in argv:
            output = f"v {tmp_path}\nv {home.parent}\n"
        else:
            target = home.parent if Path(argv[-1]).is_relative_to(home.parent) else tmp_path
            output = f"v {target}\n"
        return subprocess.CompletedProcess(argv, 0, output, "")

    resolver = partial(volume_for, run=run)
    roots = [{"path": str(home)}, {"path": str(outside)}]
    directory = tmp_path / "data"
    await reindex(roots, directory=directory, embedder=FakeEmbedder(), volume_resolver=resolver)
    service = SearchService(
        directory / "index", lambda: Settings(roots=roots), FakeEmbedder(), State(),
        volume_resolver=resolver, mounts_resolver=lambda: mounted_volumes(run=run)
    )
    try:
        reply = await service.handle({"t": "search", "seq": 1, "q": "lunar", "legs": ["words"]})
        assert {item["path"] for item in reply["items"]} == {
            str(home / "inside.txt"), str(outside / "outside.txt")
        }
        assert service.searcher.stores[0].mount == home.parent
        paths = service.searcher.stores[0].db.execute("SELECT path FROM files")
        assert {row[0] for row in paths} == {
            "u/inside.txt", "../opt/outside.txt"
        }
    finally:
        await service.stop()


def test_cli_root_reuses_configured_excludes_and_volume(cli, env, tmp_path, monkeypatch):
    import sys

    from omafindd import embedder, embedding, indexing

    root = tmp_path / "corpus"
    root.mkdir()
    settings = Path(env["HOME"]) / ".config/omarchy/shell.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"plugins": [{"id": "radimsem.omafind", "roots": [
        {"path": str(root), "excludes": ["private"], "volume": "v"}
    ]}]}))
    monkeypatch.setattr(sys, "prefix", str(Path(env["HOME"]) / ".local/share/omafind/venv"))
    monkeypatch.setattr(embedder, "Embedder", lambda **kwargs: FakeEmbedder())
    monkeypatch.setattr(embedding, "Adapter", lambda value: value)
    received = []

    async def index(roots, **kwargs):
        received.extend(roots)

    monkeypatch.setattr(indexing, "reindex", index)
    assert cli.main(["reindex", "--root", str(root / "../corpus")], env) == 0
    assert received == [{"path": str(root), "excludes": ["private"], "volume": "v"}]


@pytest.mark.parametrize("operation", ["warm", "search", "embedding"])
async def test_words_search_does_not_wait_for_server(store, tmp_path, operation):
    from omafindd.service import SearchService

    await seeded_search(store, tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()

    class Slow(FakeEmbedder):
        async def start(self, mode):
            if operation != "embedding":
                entered.set()
                await release.wait()
            await super().start(mode)

        async def embed_query(self, text):
            if operation == "embedding":
                entered.set()
                await release.wait()
            return await super().embed_query(text)

    service = SearchService(
        store.path.parent, lambda: Settings(), Slow(), State(model="ready"),
        volume_resolver=lambda path, **kwargs: ("v", tmp_path), mounts_resolver=lambda: {}
    )
    message = {"t": "warm"} if operation == "warm" else {"t": "search", "seq": 1, "q": "lunar"}
    pending = asyncio.create_task(service.handle(message))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        reply = await asyncio.wait_for(service.handle(
            {"t": "search", "seq": 2, "q": "lunar", "legs": ["words"]}
        ), 0.5)
        assert reply["items"][0]["name"] == "notes.txt"
        assert reply["legs"] == ["words"]
    finally:
        release.set()
        await pending
        await service.stop()


@pytest.mark.parametrize('startup', ['first-query', 'after-reindex', 'warm-request'])
@pytest.mark.parametrize('legs', [['words', 'meaning'], ['meaning']])
async def test_query_while_server_starting_returns_words_without_waiting(
        store, tmp_path, startup, legs):
    import fcntl

    from omafindd.service import SearchService

    await seeded_search(store, tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()

    class Slow(FakeEmbedder):
        blocked = startup != 'after-reindex'
        starts = 0

        async def start(self, mode):
            if self.mode != mode:
                self.starts += 1
                if self.blocked:
                    entered.set()
                    await release.wait()
            await super().start(mode)

    embedder = Slow()
    service = SearchService(
        store.path.parent, lambda: Settings(), embedder, State(model='ready'),
        volume_resolver=lambda path, **kwargs: ('v', tmp_path), mounts_resolver=lambda: {}
    )
    warming = None
    query = {'t': 'search', 'seq': 7, 'q': 'lunar', 'legs': legs}
    try:
        if startup == 'after-reindex':
            await service.handle({'t': 'warm'})
            with (tmp_path / 'index.lock').open('a') as lock:
                with (tmp_path / 'index.want').open('a') as want:
                    fcntl.flock(want, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    await service.yield_to_indexer()
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = await service.handle(query)
                    assert locked['degraded'] == errors.index_running().to_dict()
            embedder.blocked = True
        elif startup == 'warm-request':
            warming = asyncio.create_task(service.handle({'t': 'warm'}))
            await asyncio.wait_for(entered.wait(), .5)
        reply = await asyncio.wait_for(service.handle(query), .1)
        await asyncio.wait_for(entered.wait(), .5)
        assert not release.is_set()
        assert reply['legs'] == ['words']
        assert reply['degraded'] == errors.server_starting().to_dict()
        assert reply['items'][0]['name'] == 'notes.txt'
        assert reply['items'][0]['leg'] == 'words'
        repeated = await asyncio.wait_for(service.handle(query), .1)
        assert repeated['legs'] == ['words']
        assert embedder.starts == (2 if startup == 'after-reindex' else 1)
        release.set()
        await service.handle({'t': 'warm'})
        ready = await service.handle(query)
        assert ready['seq'] == 7 and ready['legs'] == legs
        assert ready['degraded'] is None
    finally:
        release.set()
        if warming is not None:
            await warming
        await service.stop()


async def test_background_startup_failure_is_reported_by_next_query(store, tmp_path):
    from omafindd.embedder import EmbeddingError
    from omafindd.service import SearchService

    await seeded_search(store, tmp_path)
    release, failed = asyncio.Event(), asyncio.Event()

    class Failed(FakeEmbedder):
        starts = 0

        async def start(self, mode):
            self.starts += 1
            await release.wait()
            failed.set()
            raise EmbeddingError('the embedding server did not start')

    service = SearchService(
        store.path.parent, lambda: Settings(), Failed(), State(model='ready'),
        volume_resolver=lambda path, **kwargs: ('v', tmp_path), mounts_resolver=lambda: {}
    )
    query = {'t': 'search', 'seq': 1, 'q': 'lunar'}
    try:
        assert (await service.handle(query))['degraded'] == errors.server_starting().to_dict()
        release.set()
        await asyncio.wait_for(failed.wait(), .5)
        reply = await service.handle(query)
        assert reply['degraded'] == errors.embedding_unavailable(
            'the embedding server did not start').to_dict()
        assert reply['items'][0]['name'] == 'notes.txt'
        assert service._index_lock is None
        assert service.embedder.starts == 1
    finally:
        await service.stop()


@pytest.mark.parametrize('operation', ['stop', 'yield'])
async def test_background_startup_is_cancelled_before_releasing_index_lock(
        store, tmp_path, operation):
    import fcntl

    from omafindd.service import SearchService

    await seeded_search(store, tmp_path)
    entered, cancelled = asyncio.Event(), asyncio.Event()

    class Slow(FakeEmbedder):
        async def start(self, mode):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    service = SearchService(
        store.path.parent, lambda: Settings(), Slow(), State(model='ready'),
        volume_resolver=lambda path, **kwargs: ('v', tmp_path), mounts_resolver=lambda: {}
    )
    try:
        await service.handle({'t': 'search', 'seq': 1, 'q': 'lunar'})
        await asyncio.wait_for(entered.wait(), .5)
        with (tmp_path / 'index.want').open('a') as want:
            fcntl.flock(want, fcntl.LOCK_EX | fcntl.LOCK_NB)
            action = service.stop if operation == 'stop' else service.yield_to_indexer
            await asyncio.wait_for(action(), .1)
            with (tmp_path / 'index.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert cancelled.is_set() and service.embedder.mode is None
    finally:
        await service.stop()


async def test_client_words_reply_precedes_slow_warm(store, tmp_path):
    from omafindd.service import SearchService

    await seeded_search(store, tmp_path)
    entered, release, answered = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Slow(FakeEmbedder):
        async def start(self, mode):
            entered.set()
            await release.wait()
            await super().start(mode)

    class Writer:
        def __init__(self):
            self.replies = []

        def get_extra_info(self, name):
            return None

        def write(self, data):
            reply = json.loads(data)
            self.replies.append(reply)
            if reply.get("seq") == 2:
                answered.set()

        async def drain(self):
            pass

        def close(self):
            pass

        async def wait_closed(self):
            pass

    service = SearchService(
        store.path.parent, lambda: Settings(), Slow(), State(),
        volume_resolver=lambda path, **kwargs: ("v", tmp_path), mounts_resolver=lambda: {}
    )
    server = IpcServer(
        tmp_path / "ui.sock", service.state, peer_uid=lambda sock: os.getuid(), service=service
    )
    reader, writer = asyncio.StreamReader(), Writer()
    server._accept(reader, writer)
    reader.feed_data(b'{"t":"hello","v":1}\n{"t":"warm"}\n')
    try:
        await asyncio.wait_for(entered.wait(), 0.5)
        reader.feed_data(b'{"t":"search","seq":2,"q":"lunar","legs":["words"]}\n')
        await asyncio.wait_for(answered.wait(), 0.5)
        assert writer.replies[0]["t"] == "state"
        assert writer.replies[0]["embedder"] == "stopped"
        assert writer.replies[1]["t"] == "results"
        assert writer.replies[1]["items"][0]["name"] == "notes.txt"
        assert writer.replies[1]["legs"] == ["words"]
        assert any(not task.done() for task in server._tasks)
        reader.feed_eof()
        await asyncio.gather(*tuple(server._tasks), return_exceptions=True)
        assert service.embedder.mode is None
        assert server.resolve(writer, writer.replies[1]["items"][0]["id"]) is None
    finally:
        release.set()
        await server.stop()
        await service.stop()


@pytest.mark.parametrize("legs", [["words", "meaning"], ["meaning"], ["words"]])
async def test_reindex_lock_forces_words_and_rejects_warm(store, tmp_path, legs):
    import fcntl

    from omafindd.service import SearchService

    await seeded_search(store, tmp_path)

    class Observe(FakeEmbedder):
        starts = 0

        async def start(self, mode):
            self.starts += 1
            await super().start(mode)

    embedder = Observe()
    service = SearchService(
        store.path.parent, lambda: Settings(), embedder, State(model="ready"),
        volume_resolver=lambda path, **kwargs: ("v", tmp_path), mounts_resolver=lambda: {}
    )
    try:
        with (tmp_path / "index.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            warm = await service.handle({"t": "warm"})
            assert warm == {"t": "warm_failed", "error": errors.index_running().to_dict()}
            reply = await service.handle({"t": "search", "seq": 1, "q": "lunar", "legs": legs})
            assert reply["degraded"] == errors.index_running().to_dict()
            assert reply["legs"] == ["words"]
            assert reply["items"][0]["leg"] == "words"
            assert embedder.starts == 0
        assert (await service.handle({"t": "warm"}))["embedder"] == "text"
        assert embedder.starts == 1
    finally:
        await service.stop()


async def test_warm_server_holds_shared_index_lock_until_stopped(tmp_path):
    import fcntl

    from omafindd.service import SearchService

    service = SearchService(tmp_path / "index", lambda: Settings(), FakeEmbedder(), State())
    try:
        await service.handle({"t": "warm"})
        with (tmp_path / "index.lock").open("a") as lock:
            with pytest.raises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            await service.stop()
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        await service.stop()


async def test_tick_yields_warm_server_to_waiting_reindex_without_message(tmp_path):
    import fcntl

    from omafindd.service import SearchService

    state = State()
    service = SearchService(tmp_path / "index", lambda: Settings(), FakeEmbedder(), state)
    try:
        await service.handle({"t": "warm"})
        await service.yield_to_indexer()
        assert service.embedder.mode == state.embedder == "text"
        with (tmp_path / "index.want").open("a") as want, (
            tmp_path / "index.lock"
        ).open("a") as lock:
            fcntl.flock(want, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            await service.yield_to_indexer()
            assert service.embedder.mode is None
            assert state.embedder == "stopped"
            assert service._idle_task is None
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        await service.stop()


async def test_start_releases_warm_server_lock_when_reindex_intent_arrives(tmp_path):
    import fcntl

    from omafindd.embedder import EmbeddingError
    from omafindd.service import SearchService

    service = SearchService(tmp_path / "index", lambda: Settings(), FakeEmbedder(), State())
    try:
        await service.handle({"t": "warm"})
        with (tmp_path / "index.want").open("a") as want, (
            tmp_path / "index.lock"
        ).open("a") as lock:
            fcntl.flock(want, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(EmbeddingError, match="indexing in progress"):
                await asyncio.wait_for(service._start("text"), 0.5)
            assert service.embedder.mode is None
            assert service.state.embedder == "stopped"
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        await service.stop()


async def test_serve_tick_yields_to_reindex_without_client_message(tmp_path, monkeypatch):
    import fcntl
    from types import SimpleNamespace

    from omafindd import main

    manifest = tmp_path / "manifest.json"
    manifest.touch()
    released = asyncio.Event()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(main.paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(main.paths, "socket_path", lambda: tmp_path / "ui.sock")
    monkeypatch.setattr(main, "Embedder", lambda **kwargs: FakeEmbedder())
    monkeypatch.setattr(main, "Adapter", lambda embedder: embedder)
    monkeypatch.setattr(
        main, "SettingsReader", lambda path: SimpleNamespace(read=lambda: Settings())
    )

    with (tmp_path / "index.want").open("a") as want, (
        tmp_path / "index.lock"
    ).open("a") as lock:
        async def changed(message):
            if message["embedder"] == "stopped" and not released.is_set():
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                released.set()
                manifest.unlink()

        class Server:
            def __init__(self, path, state):
                self.state = state

            async def start(self):
                await self.service.handle({"t": "warm"})
                fcntl.flock(want, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.state.on_change = changed

            async def broadcast(self, message):
                pass

            async def stop(self):
                pass

        monkeypatch.setattr(main, "IpcServer", Server)
        pending = asyncio.create_task(main._serve(manifest, interval=0.01))
        try:
            await asyncio.wait_for(released.wait(), 0.5)
            assert await asyncio.wait_for(pending, 0.5) == 0
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


async def test_waiting_reindex_stops_warm_server_and_holds_intent(tmp_path, monkeypatch, capsys):
    import fcntl
    import threading

    from omafindd.indexing import reindex
    from omafindd.service import SearchService

    store = Store(tmp_path / "index/v.sqlite", volume="v", mount=tmp_path)
    await seeded_search(store, tmp_path)
    store.close()
    service = SearchService(
        tmp_path / "index", lambda: Settings(), FakeEmbedder(), State(model="ready"),
        volume_resolver=lambda path, **kwargs: ("v", tmp_path), mounts_resolver=lambda: {}
    )
    wanted, acquired, release = threading.Event(), threading.Event(), threading.Event()
    flock = fcntl.flock

    def observe(file, operation):
        descriptor = file if isinstance(file, int) else file.fileno()
        path = os.readlink(f"/proc/self/fd/{descriptor}")
        if operation == fcntl.LOCK_EX and path == str(tmp_path / "index.lock"):
            assert wanted.is_set(), "reindex blocked without announcing its intent"
        result = flock(file, operation)
        if operation == fcntl.LOCK_EX and path == str(tmp_path / "index.want"):
            wanted.set()
        return result

    class Indexer(FakeEmbedder):
        async def stop(self):
            acquired.set()
            release.wait(2)
            await super().stop()

    raised = []

    def index():
        try:
            asyncio.run(reindex([], directory=tmp_path, embedder=Indexer()))
        except BaseException as error:
            raised.append(error)

    async def wait(event):
        for _ in range(100):
            if event.is_set() or raised:
                break
            await asyncio.sleep(0.01)
        if raised:
            raise raised[0]
        assert event.is_set()

    monkeypatch.setattr(fcntl, "flock", observe)
    await service.handle({"t": "warm"})
    pending = threading.Thread(target=index)
    pending.start()
    try:
        await wait(wanted)
        await service.yield_to_indexer()
        assert service.state.embedder == "stopped"
        await wait(acquired)
        reply = await service.handle({"t": "search", "seq": 1, "q": "lunar"})
        assert reply["legs"] == ["words"]
        assert reply["degraded"] == errors.index_running().to_dict()
        assert reply["items"][0]["name"] == "notes.txt"
        assert service.embedder.mode is None
        assert await service.handle({"t": "warm"}) == {
            "t": "warm_failed", "error": errors.index_running().to_dict()
        }
        assert capsys.readouterr().err.splitlines() == [
            "waiting index.lock", "queued 0"
        ]
        release.set()
        pending.join(2)
        assert not pending.is_alive()
        assert (await service.handle({"t": "warm"}))["embedder"] == "text"
        assert (tmp_path / "index.want").stat().st_mode & 0o777 == 0o600
    finally:
        release.set()
        await service.stop()
        pending.join(2)


async def test_cancelled_stop_keeps_index_lock_until_server_has_stopped(tmp_path):
    import fcntl

    from omafindd.service import SearchService

    entered, release = asyncio.Event(), asyncio.Event()

    class SlowStop(FakeEmbedder):
        async def stop(self):
            entered.set()
            await release.wait()
            await super().stop()

    service = SearchService(tmp_path / "index", lambda: Settings(), SlowStop(), State())
    await service.handle({"t": "warm"})
    stopping = asyncio.create_task(service._stop())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        stopping.cancel()
        await asyncio.sleep(0)
        with (tmp_path / "index.lock").open("a") as lock:
            with pytest.raises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            release.set()
            await asyncio.gather(stopping, return_exceptions=True)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert service.embedder.mode is None
    finally:
        release.set()
        await asyncio.gather(stopping, return_exceptions=True)
        await service.stop()


@pytest.mark.parametrize("error", [
    sqlite3.OperationalError("no such table: meta"), KeyError("meta")
])
async def test_service_exception_replies_with_error_and_keeps_connection(tmp_path, error):
    answered = asyncio.Event()

    class FailedOnce:
        calls = 0

        async def handle(self, message):
            self.calls += 1
            if self.calls == 1:
                raise error
            return {"t": "results", "seq": message["seq"], "items": []}

    class Writer:
        def __init__(self):
            self.data = bytearray()

        def get_extra_info(self, name):
            return None

        def write(self, data):
            self.data.extend(data)
            if json.loads(data).get("seq") == 8:
                answered.set()

        async def drain(self):
            pass

        def close(self):
            pass

        async def wait_closed(self):
            pass

    server = IpcServer(
        tmp_path / "ui.sock", State(), peer_uid=lambda sock: os.getuid(), service=FailedOnce()
    )
    reader, writer = asyncio.StreamReader(), Writer()
    reader.feed_data(b'{"t":"hello","v":1}\n{"t":"search","seq":7}\n{"t":"search","seq":8}\n')
    client = asyncio.create_task(server._client(reader, writer))
    try:
        await asyncio.wait_for(answered.wait(), 0.5)
    finally:
        reader.feed_eof()
        await client
    replies = [json.loads(line) for line in writer.data.splitlines()]
    assert replies[1] == {"t": "error", "seq": 7, **errors.internal(str(error)).to_dict()}
    assert replies[2] == {"t": "results", "seq": 8, "items": []}


def test_cli_service_error_prints_title_and_detail_and_exits_one(cli, env, capsys):
    reply = {"t": "error", "seq": 1, **errors.internal("no such table: meta").to_dict()}
    assert cli.main(["search", "--json", "lunar"], env, request=lambda *args: reply) == 1
    assert capsys.readouterr().err == (
        "Something failed inside the omafind service. No such table: meta.\n")


@pytest.mark.parametrize("kinds", [None, "image", ["img"], [1], [{}]])
async def test_service_rejects_invalid_kinds(tmp_path, kinds):
    from omafindd.service import SearchService

    service = SearchService(tmp_path / "index", lambda: Settings(), FakeEmbedder(), State())
    try:
        reply = await service.handle({"t": "search", "seq": 1, "q": "needle", "kinds": kinds})
        assert reply == {"t": "error", "seq": 1,
                         **errors.bad_request("Invalid search arguments").to_dict()}
    finally:
        await service.stop()


async def test_service_passes_kinds_and_configured_limit(store, tmp_path):
    from omafindd.service import SearchService
    from test_search import add

    await seeded_search(store, tmp_path)
    for i in range(11):
        await add(store, tmp_path / f"note{i}.txt", "lunar eclipse")
    service = SearchService(store.path.parent, lambda: Settings(max_results=10),
                            FakeEmbedder(), State(),
                            volume_resolver=lambda path, **kw: ("v", tmp_path))
    try:
        reply = await service.handle({"t": "search", "seq": 1, "q": "lunar",
                                      "legs": ["words"], "kinds": ["pdf"]})
        assert reply["items"] == []
        assert reply["total"] == 0
        reply = await service.handle({"t": "search", "seq": 2, "q": "lunar",
                                      "legs": ["words"]})
        assert len(reply["items"]) == 10
        assert reply["total"] == 12
    finally:
        await service.stop()


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
