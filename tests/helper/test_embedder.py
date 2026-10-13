import asyncio
import subprocess
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from fakes.embedder import FakeEmbedder
from fakes.llama_server import FakeSpawner, MemoryLlamaServer
from omafindd import embedder as embedder_module
from omafindd.embedder import (
    Embedder,
    EmbeddingError,
    ImageUrl,
    InputAudio,
    Text,
    build_command,
    build_request,
    choose_device,
    document_text,
    free_vram,
    query_text,
    server_argv,
)


@pytest.fixture(autouse=True)
def inline_runner(monkeypatch):
    # The runners are in-process fakes, so they do not need a worker thread.
    async def to_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(embedder_module.asyncio, 'to_thread', to_thread)


@pytest.mark.parametrize(('mode', 'free_mib', 'expected'), [
    ('full', 1536, 'gpu'), ('full', 1535, 'cpu'),
    ('text', 512, 'gpu'), ('text', 511, 'cpu'),
    ('text', None, 'gpu'), ('full', None, 'gpu'),
])
def test_device_thresholds(mode, free_mib, expected):
    assert choose_device(mode, free_mib) == expected


def test_free_vram_runs_nvidia_smi():
    def run(argv, **kwargs):
        assert argv == ['nvidia-smi', '--query-gpu=memory.free',
                        '--format=csv,noheader,nounits']
        return subprocess.CompletedProcess(argv, 0, stdout='2048\n')

    assert free_vram(run) == 2048


@pytest.mark.parametrize('output', ['', 'N/A', '512\n1024\n'])
def test_unknown_vram_returns_none(output):
    assert free_vram(lambda *a, **kw: subprocess.CompletedProcess(a, 0, output)) is None


def test_failed_nvidia_smi_returns_none():
    def run(*args, **kwargs):
        raise FileNotFoundError('nvidia-smi')

    assert free_vram(run) is None


def test_command_builder_selects_models_and_cpu_nice(tmp_path):
    full = build_command('/runtime/llama-server', tmp_path, 'full', 'cpu', 1234)
    assert full == [
        'nice', '-n', '19', '/runtime/llama-server',
        '-m', str(tmp_path / 'embeddinggemma-2-Q8_0.gguf'),
        '--mmproj', str(tmp_path / 'mmproj-embeddinggemma-2-Q8_0.gguf'),
        '--embeddings', '--pooling', 'mean', '--host', '127.0.0.1', '--port', '1234',
        '--ctx-size', '2048', '--batch-size', '2048',
        '--ubatch-size', '2048', '--parallel', '16', '--kv-unified',
        '--image-min-tokens', '1', '--no-mmproj-offload', '-ngl', '0',
    ]
    text = build_command('/runtime/llama-server', tmp_path, 'text', 'gpu', 1234)
    assert text[0] == '/runtime/llama-server'
    assert '--mmproj' not in text
    assert text[-2:] == ['-ngl', '99']
    assert text[text.index('--ctx-size') + 1] == '512'
    assert server_argv('llama-server', '/model.gguf', None, 1234, 'gpu') == [
        'llama-server', '-m', '/model.gguf', '--embeddings', '--pooling', 'mean',
        '--host', '127.0.0.1', '--port', '1234',
        '--ctx-size', '512', '--batch-size', '512', '--ubatch-size', '512',
        '--parallel', '16', '--kv-unified', '-ngl', '99',
    ]


def test_request_builder_uses_typed_parts():
    assert build_request([Text('hello'), ImageUrl('data:image/png;base64,abc'),
                          InputAudio('YWJj', 'wav')]) == {'input': [
        {'content': [{'type': 'text', 'text': 'hello'}]},
        {'content': [{'type': 'image_url',
                      'image_url': {'url': 'data:image/png;base64,abc'}}]},
        {'content': [{'type': 'input_audio',
                      'input_audio': {'data': 'YWJj', 'format': 'wav'}}]},
    ], 'encoding_format': 'float'}


def test_prompt_helpers():
    assert query_text('a cat') == 'task: search result | query: a cat'
    assert document_text('note.md', 'some text') == 'title: note.md | text: some text'


@pytest.fixture
def runtime(tmp_path):
    spawner = FakeSpawner()

    def runner(*a, **kw):
        return subprocess.CompletedProcess(a, 0, '4096')

    embedder = Embedder(binary='/runtime/llama-server', model_dir=tmp_path,
                        runner=runner, spawner=spawner, startup_timeout=0.2,
                        stop_timeout=0.01)
    try:
        yield embedder, spawner
    finally:
        spawner.close()


@pytest.fixture
def memory_runtime(runtime, monkeypatch):
    embedder, spawner = runtime
    spawner.server_factory = MemoryLlamaServer
    embedder.startup_timeout = 1
    client = httpx.AsyncClient

    @contextmanager
    def socket():
        yield SimpleNamespace(bind=lambda address: None,
                              getsockname=lambda: ('127.0.0.1', 1234))

    def make_client(**kwargs):
        return client(**kwargs, transport=httpx.MockTransport(spawner.servers[-1].handle))

    monkeypatch.setattr(embedder_module, 'socket', SimpleNamespace(socket=socket))
    monkeypatch.setattr(embedder_module.httpx, 'AsyncClient', make_client)
    return embedder, spawner


async def test_spawn_key_is_only_in_environment_and_authenticates(memory_runtime, monkeypatch):
    embedder, spawner = memory_runtime
    monkeypatch.setenv('OMAFIND_TEST_INHERITED', 'inherited')
    await embedder.start('text')
    await embedder.embed([Text('hello')])
    await embedder.start('full')
    await embedder.embed([Text('hello')])
    for command, env, server in zip(spawner.commands, spawner.environments,
                                    spawner.servers, strict=True):
        assert '--api-key' not in command
        assert server.api_key not in command
        assert env['LLAMA_API_KEY'] == server.api_key
        assert env['OMAFIND_TEST_INHERITED'] == 'inherited'
        assert all(row[1] == f'Bearer {server.api_key}' for row in server.requests)
    assert spawner.servers[0].api_key != spawner.servers[1].api_key
    await embedder.stop()


async def test_spawn_sets_parent_death_sigterm(memory_runtime, monkeypatch):
    import ctypes
    import os
    import signal

    embedder, spawner = memory_runtime
    options = []
    calls = []

    async def spawn(*argv, **kwargs):
        options.append(kwargs)
        return await spawner(*argv, **kwargs)

    monkeypatch.setattr(ctypes, "CDLL", lambda *args, **kwargs: SimpleNamespace(
        prctl=lambda *args: calls.append(args) or 0
    ))
    monkeypatch.setattr(os, "getppid", os.getpid)
    embedder.spawner = spawn
    try:
        await embedder.start("full")
        options[0]["preexec_fn"]()
        assert calls == [(1, signal.SIGTERM, 0, 0, 0)]
        assert "--mmproj" in spawner.commands[0]
    finally:
        await embedder.stop()


async def test_concurrent_mode_start_waits_for_health_before_replacing_server(memory_runtime):
    embedder, spawner = memory_runtime
    spawner.server_options['health_status'] = 503
    first = asyncio.create_task(embedder.start('text'))
    second = None
    try:
        async with asyncio.timeout(1):
            while not spawner.servers:
                await asyncio.sleep(0)
            server = spawner.servers[0]
            await server.health_requested.wait()
        spawner.server_options['health_status'] = 200
        second = asyncio.create_task(embedder.start('full'))
        await asyncio.sleep(0)
        assert not server.terminated
        assert len(spawner.servers) == 1
        server.health_status = 200
        await asyncio.wait_for(asyncio.gather(first, second), 1)
        assert server.terminated
        assert len(spawner.servers) == 2
        assert embedder.mode == 'full'
        assert len(await embedder.embed([Text('hello')])) == 1
        await embedder.stop()
        assert all(server.returncode is not None for server in spawner.servers)
    finally:
        tasks = [task for task in (first, second) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await embedder.stop()


async def test_stop_waits_for_every_embedding_batch(memory_runtime):
    embedder, spawner = memory_runtime
    await embedder.start('text')
    server = spawner.servers[0]
    server.embedding_release.clear()
    embedding = asyncio.create_task(embedder.embed([Text(str(i)) for i in range(17)]))
    stopping = None
    try:
        await asyncio.wait_for(server.embedding_requested.get(), 1)
        stopping = asyncio.create_task(embedder.stop())
        await asyncio.sleep(0)
        assert not server.terminated
        assert not stopping.done()
        server.embedding_release.set()
        vectors = await asyncio.wait_for(embedding, 1)
        await asyncio.wait_for(stopping, 1)
        assert len(vectors) == 17
        assert [len(row[2]['input']) for row in server.requests if row[2]] == [16, 1]
        assert server.terminated
        with pytest.raises(EmbeddingError, match='not running'):
            await embedder.embed([Text('hello')])
    finally:
        server.embedding_release.set()
        tasks = [task for task in (embedding, stopping) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await embedder.stop()


@pytest.mark.parametrize('error', [httpx.ReadError('Connection lost'),
                                  RuntimeError('Client is closed')])
async def test_embedding_transport_failure_is_embedding_error(memory_runtime, error):
    embedder, spawner = memory_runtime
    await embedder.start('text')
    spawner.servers[0].request_error = error
    try:
        with pytest.raises(EmbeddingError, match='^Embedding request failed$'):
            await embedder.embed([Text('hello')])
    finally:
        await embedder.stop()


async def test_server_exit_during_embedding_is_embedding_error(memory_runtime):
    embedder, spawner = memory_runtime
    await embedder.start('text')
    server = spawner.servers[0]
    server.embedding_release.clear()
    embedding = asyncio.create_task(embedder.embed([Text(str(i)) for i in range(17)]))
    try:
        await asyncio.wait_for(server.embedding_requested.get(), 1)
        server.close()
        server.embedding_release.set()
        with pytest.raises(EmbeddingError, match='not running'):
            await asyncio.wait_for(embedding, 1)
    finally:
        embedding.cancel()
        await asyncio.gather(embedding, return_exceptions=True)
        await embedder.stop()


@pytest.mark.parametrize('body,message', [
    ('not json', 'Invalid embedding response'),
    ('{"data": []}', 'Invalid embedding response'),
    ('{"data": [{"index": 0}]}', 'Invalid embedding response'),
    ('{"data": [{"index": 0, "embedding": [1.0]}]}', 'embedding precision fault'),
])
async def test_only_bad_vectors_are_precision_faults(memory_runtime, body, message):
    embedder, spawner = memory_runtime

    class ResponseServer(MemoryLlamaServer):
        async def handle(self, request):
            response = await super().handle(request)
            if request.url.path == '/v1/embeddings':
                return httpx.Response(200, content=body)
            return response

    spawner.server_factory = ResponseServer
    await embedder.start('text')
    try:
        with pytest.raises(EmbeddingError, match=f'^{message}$'):
            await embedder.embed([Text('hello')])
    finally:
        await embedder.stop()


async def test_embed_splits_batches_authenticates_and_returns_float16(runtime):
    embedder, spawner = runtime
    await embedder.start('full')
    vectors = await embedder.embed([Text(str(i)) for i in range(17)])
    server = spawner.servers[0]
    requests = [row for row in server.requests if row[2] is not None]
    assert [len(row[2]['input']) for row in requests] == [16, 1]
    assert all(row[0] == '/v1/embeddings' for row in requests)
    assert all(row[1] == f'Bearer {server.api_key}' for row in server.requests)
    assert len(vectors) == 17
    assert all(v.dtype == np.float16 and v.shape == (768,) for v in vectors)
    assert all(abs(float(np.linalg.norm(v.astype(np.float32))) - 1) < 1e-3 for v in vectors)
    await embedder.stop()


@pytest.mark.parametrize('vector', [
    [1.0] + [0.0] * 766,
    [float('nan')] + [0.0] * 767,
    [2.0] + [0.0] * 767,
    [0.0] * 768,
])
async def test_precision_fault_is_rejected(runtime, vector):
    embedder, spawner = runtime
    spawner.server_options['vector'] = vector
    await embedder.start('text')
    with pytest.raises(EmbeddingError, match='^embedding precision fault$'):
        await embedder.embed([Text('hello')])
    await embedder.stop()


async def test_vectors_follow_response_indexes_and_are_normalized(runtime):
    embedder, spawner = runtime
    spawner.server_options['reverse'] = True
    await embedder.start('text')
    vectors = await embedder.embed([Text('first'), Text('second')])
    assert np.argmax(vectors[0]) == 0
    assert np.argmax(vectors[1]) == 1
    spawner.servers[0].vector = [1.0005] + [0.0] * 767
    assert (await embedder.embed([Text('near unit')]))[0][0] == 1
    await embedder.stop()


async def test_mode_switch_stops_previous_process_and_rotates_key(runtime):
    embedder, spawner = runtime
    await embedder.start('text')
    await embedder.start('text')
    assert len(spawner.commands) == 1
    await embedder.start('full')
    assert spawner.servers[0].terminated
    assert spawner.servers[0].api_key != spawner.servers[1].api_key
    assert '--mmproj' in spawner.commands[1]
    await embedder.stop()
    await embedder.stop()


async def test_stop_kills_after_grace_period(runtime):
    embedder, spawner = runtime
    spawner.server_options['ignore_terminate'] = True
    await embedder.start('text')
    await embedder.stop()
    assert spawner.servers[0].terminated
    assert spawner.servers[0].killed


async def test_unknown_vram_retries_failed_gpu_once_on_cpu(tmp_path):
    spawner = FakeSpawner()

    async def spawn(*argv, **kwargs):
        spawner.server_options['health_status'] = 503 if argv[-1] == '99' else 200
        return await spawner(*argv, **kwargs)

    def runner(*args, **kwargs):
        raise FileNotFoundError('nvidia-smi')

    embedder = Embedder(binary='llama-server', model_dir=tmp_path, runner=runner,
                        spawner=spawn, startup_timeout=0.05)
    try:
        await embedder.start('full')
        assert len(spawner.commands) == 2
        assert spawner.commands[1][:3] == ['nice', '-n', '19']
        assert spawner.servers[0].terminated
        assert spawner.servers[0].api_key != spawner.servers[1].api_key
        await embedder.stop()
    finally:
        spawner.close()


async def test_known_vram_start_failure_does_not_retry(runtime):
    embedder, spawner = runtime
    spawner.server_options['health_status'] = 503
    with pytest.raises(EmbeddingError, match='start'):
        await embedder.start('text')
    assert len(spawner.commands) == 1
    assert spawner.servers[0].terminated


async def test_empty_batch_makes_no_request(runtime):
    embedder, spawner = runtime
    await embedder.start('text')
    requests = len(spawner.servers[0].requests)
    assert await embedder.embed([]) == []
    assert len(spawner.servers[0].requests) == requests
    await embedder.stop()


async def test_embed_requires_started_server(runtime):
    embedder, _ = runtime
    with pytest.raises(EmbeddingError, match='not running'):
        await embedder.embed([Text('hello')])


async def test_media_parts_use_typed_content_over_http(runtime):
    embedder, spawner = runtime
    await embedder.start('full')
    await embedder.embed([ImageUrl('data:image/png;base64,YWJj'), InputAudio('YWJj', 'wav')])
    assert spawner.servers[0].requests[-1][2] == {
        'input': [
            {'content': [{'type': 'image_url',
                          'image_url': {'url': 'data:image/png;base64,YWJj'}}]},
            {'content': [{'type': 'input_audio',
                          'input_audio': {'data': 'YWJj', 'format': 'wav'}}]},
        ],
        'encoding_format': 'float',
    }
    await embedder.stop()


async def test_key_rotates_after_stop_and_restart(runtime):
    embedder, spawner = runtime
    await embedder.start('text')
    await embedder.stop()
    await embedder.start('text')
    assert spawner.servers[0].api_key != spawner.servers[1].api_key
    await embedder.stop()


async def test_fake_embedder_provides_repeatable_unit_vectors():
    parts = [Text('hello'), ImageUrl('data:image/png;base64,YWJj'), InputAudio('YWJj', 'wav')]
    embedder = FakeEmbedder()
    await embedder.start('full')
    first = await embedder.embed(parts)
    second = await FakeEmbedder().embed(parts)
    assert all(vector.shape == (768,) and vector.dtype == np.float16 for vector in first)
    assert all(float(np.linalg.norm(vector.astype(np.float32))) == 1 for vector in first)
    assert all(np.array_equal(a, b) for a, b in zip(first, second, strict=True))
    assert not np.array_equal(first[0], first[1])
    await embedder.stop()


async def test_client_only_embedder_never_spawns_or_stops_server(memory_runtime, monkeypatch):
    owner, spawner = memory_runtime
    await owner.start('full')
    env = owner.connection_env
    shared = Embedder(base_url=env['OMAFIND_EMBED_URL'], api_key=env['OMAFIND_EMBED_KEY'],
                      spawner=lambda *args, **kwargs: pytest.fail('client spawned a server'))
    try:
        await shared.start('full')
        assert len(await shared.embed([ImageUrl('data:image/png;base64,YWJj')])) == 1
        await shared.stop()
        assert owner.mode == 'full'
        assert not spawner.servers[0].terminated
        assert len(await owner.embed([Text('still warm')])) == 1
    finally:
        await shared.stop()
        await owner.stop()


async def test_full_server_serves_text_without_restart(memory_runtime):
    embedder, spawner = memory_runtime
    await embedder.start('full')
    try:
        await embedder.start('text')
        assert embedder.mode == 'full'
        assert len(spawner.commands) == 1
        assert len(await embedder.embed([Text('query')])) == 1
    finally:
        await embedder.stop()


async def test_lease_reuses_daemon_server_while_it_is_starting(memory_runtime, monkeypatch):
    from omafindd import main
    from omafindd.embedding import Adapter
    from omafindd.service import SearchService
    from omafindd.settings import Settings
    from omafindd.state import State

    embedder, spawner = memory_runtime
    spawner.server_options['health_status'] = 503
    monkeypatch.setattr(main, 'Embedder', lambda **kwargs: embedder)
    service = SearchService(embedder.model_dir / 'index', lambda: Settings(),
                            main._LazyEmbedder(), State(model='ready'))
    warming = service._warming('text')
    leasing = None
    try:
        async with asyncio.timeout(1):
            while not spawner.servers:
                await asyncio.sleep(0)
            server = spawner.servers[0]
            await server.health_requested.wait()
        leasing = asyncio.create_task(service.lease_indexer())
        await asyncio.sleep(0)
        server.health_status = 200
        env = await asyncio.wait_for(leasing, 1)
        assert await warming is None
        assert env['OMAFIND_EMBED_KEY'] == server.api_key
        assert len(spawner.commands) == 1
        assert '--mmproj' in spawner.commands[0]
        assert not server.terminated
        await service._start('text')
        assert len(await Adapter(embedder).embed_query('fixture')) == 768
    finally:
        server.health_status = 200
        tasks = [task for task in (warming, leasing) if task is not None]
        await asyncio.gather(*tasks, return_exceptions=True)
        await service.release_indexer()
        await service.stop()


@pytest.mark.parametrize('url', [
    None, '', 'https://127.0.0.1:8080', 'http://example.com:8080', 'http://10.0.0.2:8080',
    'http://127.0.0.1', 'http://localhost:8080', 'http://u:p@127.0.0.1:8080',
    'http://127.0.0.1:8080/v1', 'http://127.0.0.1:8080?x=1', 'http://[::1]:8080', 'not a url',
])
def test_shared_server_url_must_be_loopback(url):
    from omafindd.embedder import loopback_url

    assert loopback_url(url) is None


def test_shared_server_url_accepts_daemon_loopback():
    from omafindd.embedder import loopback_url

    assert loopback_url('http://127.0.0.1:42065') == 'http://127.0.0.1:42065'
