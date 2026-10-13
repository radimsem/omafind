import json
import os
import signal
import subprocess
import sys
import textwrap
from concurrent.futures import Future
from pathlib import Path

from fakes.embedder import FakeEmbedder
from omafindd.crawler import crawl
from omafindd.jobs import Jobs
from omafindd.store import Store


def test_leftover_running_file_triggers_rewalk(tmp_path):
    from omafindd.recovery import begin, end

    first = begin(tmp_path)
    assert first.clean and first.journal_files == 0
    assert (tmp_path / 'running').stat().st_mode & 0o777 == 0o600
    (tmp_path / 'journal').write_text(
        '{"b":1,"volume":"v","files":[1,2]}\n'
        '{"b":2,"volume":"v","files":[2]}\n')
    second = begin(tmp_path)
    assert not second.clean and second.journal_files == 2
    end(tmp_path)
    end(tmp_path)
    assert begin(tmp_path).clean
    end(tmp_path)


async def test_kill_mid_batch_retries_only_inflight_batch(tmp_path, monkeypatch):
    root = tmp_path / 'docs'
    root.mkdir()
    for name in ('one.txt', 'two.txt'):
        (root / name).write_text('lunar eclipse fixture')
    path, journal = tmp_path / 'index/v.sqlite', tmp_path / 'journal'
    store = Store(path, volume='v', mount=root)
    try:
        first, second = sorted(crawl(store, [{'path': str(root)}]))
        with store.db:
            store.db.execute("UPDATE files SET state='done'")
            store.db.execute("UPDATE files SET state='pending' WHERE id=?", (second,))
    finally:
        store.close()
    script = textwrap.dedent('''
        import asyncio, json, sys
        from concurrent.futures import Future
        from pathlib import Path
        from omafindd import jobs
        from omafindd.store import Store
        from fakes.embedder import FakeEmbedder

        class Pool:
            def submit(self, function, *args):
                future = Future()
                future.set_result(function(*args))
                return future
            def shutdown(self, **kwargs):
                pass

        class Blocked(FakeEmbedder):
            async def embed_documents(self, parts):
                print(json.dumps({'inflight': int(sys.argv[4])}), flush=True)
                await asyncio.Future()

        jobs._pool = Pool
        store = Store(Path(sys.argv[1]), volume='v', mount=Path(sys.argv[2]))
        asyncio.run(jobs.Jobs(store, Blocked(), journal=Path(sys.argv[3])).drain(
            only=[int(sys.argv[4])]))
    ''')
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join([
        str(Path(__file__).parents[2] / 'helper'), str(Path(__file__).parents[1])])}
    argv = [sys.executable, '-c', script, str(path), str(root), str(journal), str(second)]
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, env=env) as parent:
        try:
            assert json.loads(parent.stdout.readline()) == {'inflight': second}
            parent.send_signal(signal.SIGKILL)
            parent.wait(timeout=5)
            assert parent.returncode == -signal.SIGKILL
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait(timeout=5)
    store = Store(path, volume='v', mount=root)
    try:
        retry = Jobs(store, FakeEmbedder(), journal=journal)
        assert retry.recover() == [second]
        state = store.db.execute('SELECT state FROM files WHERE id=?', (first,)).fetchone()[0]
        assert state == 'done'

        class Pool:
            def submit(self, function, *args):
                future = Future()
                future.set_result(function(*args))
                return future

            def shutdown(self, **kwargs):
                pass

        monkeypatch.setattr('omafindd.jobs._pool', Pool)
        events = []
        await retry.drain(progress=events.append)
        assert len(events) == 1 and events[0]['state'] == 'done'
        assert journal.read_text() == ''
    finally:
        store.close()


async def test_pause_awaited_before_each_embedding_batch(tmp_path, monkeypatch):
    from omafindd.extractors import Extracted, Segment

    root = tmp_path / 'docs'
    root.mkdir()
    (root / 'long.txt').write_text('fixture')
    store = Store(tmp_path / 'index/v.sqlite', volume='v', mount=root)
    order = []

    class Pool:
        def submit(self, *args):
            future = Future()
            future.set_result(Extracted(
                [Segment('chunk', 'text', 'fixture') for _ in range(33)], {}))
            return future

        def shutdown(self, **kwargs):
            pass

    class Observe(FakeEmbedder):
        async def embed_documents(self, parts):
            order.append(('embed', len(parts)))
            return await super().embed_documents(parts)

    async def pause():
        order.append(('pause', None))

    monkeypatch.setattr('omafindd.jobs._pool', Pool)
    try:
        crawl(store, [{'path': str(root)}])
        await Jobs(store, Observe(), journal=tmp_path / 'journal', pause=pause).drain()
        assert order == [('pause', None), ('embed', 16), ('pause', None), ('embed', 16),
                         ('pause', None), ('embed', 1)]
    finally:
        store.close()
