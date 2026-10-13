import json
import subprocess

import pytest
from fakes.embedder import FakeEmbedder


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def tracked(repo, name, body):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    subprocess.run(["git", "-C", str(repo), "add", "-f", "--", name], check=True)
    return path


async def test_index_tracked_eligible_files_only(repo, tmp_path):
    import sqlite3

    from omafindd.code import index_code

    tracked(repo, "retry.py", "def retry_with_backoff():\n    return 1\n")
    for name, body in [
        ("vendor/other.py", "retry backoff"), ("generated.py", "# @generated\nretry"),
        ("bundle.js", "x" * 3100), ("key.py", "PRIVATE KEY-----"),
        (".env", "invented fixture"), ("test.pem", "invented fixture"),
        ("LICENSE.md", "terms"), ("data.json", "{}"), ("app.min.js", "x"),
    ]:
        tracked(repo, name, body)
    (repo / "untracked.py").write_text("retry backoff")
    tracked(repo, "linked.py", "retry")
    (repo / "linked.py").unlink()
    (repo / "linked.py").symlink_to(repo / "retry.py")
    subprocess.run(["git", "-C", str(repo), "add", "linked.py"], check=True)
    # A gitlink can exist without checking out its submodule.
    subprocess.run(["git", "-C", str(repo), "update-index", "--add", "--cacheinfo",
                    "160000,0123456789012345678901234567890123456789,submodule"], check=True)
    await index_code([repo], tmp_path / "index", FakeEmbedder())
    with sqlite3.connect(tmp_path / "index/code.sqlite") as db:
        assert [row[0] for row in db.execute("SELECT path FROM files")] == [
            str(repo / "retry.py").lstrip("/")
        ]
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='fts'").fetchall()
        row = db.execute("SELECT loc,loc_end,length(vec),excerpt FROM segments").fetchone()
        assert row[:3] == (1, 2, 1536)
        assert row[3].startswith("def retry_with_backoff")


async def test_incremental_changed_removed_and_no_long_text_storage(repo, tmp_path):
    import sqlite3

    from omafindd.code import index_code

    class Counting(FakeEmbedder):
        calls = 0
        async def embed_documents(self, texts):
            self.calls += 1
            assert all(text.startswith("title: repo/") for text in texts)
            return await super().embed_documents(texts)

    embedder = Counting()
    path = tracked(repo, "one.py", "def first():\n    pass\n")
    await index_code([repo], tmp_path / "index", embedder)
    await index_code([repo], tmp_path / "index", embedder)
    assert embedder.calls == 1
    path.write_text("def changed():\n    return 'changed'\n")
    await index_code([repo], tmp_path / "index", embedder)
    assert embedder.calls == 2
    path.write_text("# @generated\ndef changed(): pass")
    await index_code([repo], tmp_path / "index", embedder)
    with sqlite3.connect(tmp_path / "index/code.sqlite") as db:
        assert db.execute("SELECT count(*) FROM files").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM segments").fetchone()[0] == 0


def test_stretches_cover_code_and_overlap_mid_block():
    from omafindd.code import lines

    source = [f"    call_{n}({repr('x' * 40)})" for n in range(100)]
    pieces = lines("\n".join(source))
    assert all(len(piece.text) <= 1800 for piece in pieces)
    assert set(range(1, 101)) == {
        line for piece in pieces for line in range(piece.first, piece.last + 1)
    }
    assert pieces[1].first == pieces[0].last - 1
    assert pieces[0].text.splitlines()[-2:] == pieces[1].text.splitlines()[:2]


def test_natural_cut_and_notebook_cells():
    from omafindd.code import cells, lines, notebook_cells

    source = "def first():\n" + "    pass\n" * 120 + "\ndef second():\n" + "    pass\n" * 100
    pieces = lines(source)
    assert pieces[1].first == 123
    raw = json.dumps({"cells": [
        {"source": ["# note\n"], "outputs": ["discard me"]},
        {"source": ""}, {"source": ["def f():\n", "    pass"]},
    ]}).encode()
    pieces = cells(notebook_cells(raw))
    assert [(piece.first, piece.last) for piece in pieces] == [(1, 3)]
    assert "discard me" not in pieces[0].text
    assert cells(["x" * 1000, "y" * 1000])[1].first == 2
    assert all(piece.first == piece.last == 1 for piece in cells(["    x\n" * 600]))


async def test_words_ranking_scope_and_identifier(repo, tmp_path):
    from omafindd.code import index_code
    from omafindd.search import Searcher
    from omafindd.store import Store

    both = tracked(repo, "both.py", "def retry_with_backoff():\n    return retry(backoff)\n")
    tracked(repo, "one.py", "def retry():\n    pass\n")
    tracked(repo, "vendor/bad.py", "retry backoff")
    tracked(repo, ".gitignore", "ignored.py\n")
    tracked(repo, "ignored.py", "retry backoff")
    tracked(repo, ".env", "retry backoff")
    tracked(repo, "CERT.PEM", "retry backoff")
    (repo / "untracked.py").write_text("retry backoff")
    await index_code([repo], tmp_path / "index", FakeEmbedder())
    store = Store(tmp_path / "index/plain.sqlite", volume="plain", mount=tmp_path)
    try:
        searcher = Searcher([store], FakeEmbedder(), code_directory=tmp_path / "index",
                            code_roots=[repo])
        reply = await searcher.search("code: retry backoff", legs=["words"])
        assert [item["name"] for item in reply["items"]] == ["both.py", "one.py"]
        assert reply["items"][0]["path"] == str(both)
        assert reply["items"][0]["kind"] == "code"
        assert reply["items"][0]["open_line"] == 1
        assert reply["items"][0]["loc_end"] == 2
        assert reply["items"][0]["snippet"]
        identifier = await searcher.search("code: retry_with_backoff", legs=["words"])
        assert [item["name"] for item in identifier["items"]] == ["both.py"]
        assert identifier["items"][0]["score"] == 4
        assert (await searcher.search("retry backoff"))["items"] == []
        both.write_text("PRIVATE KEY-----\nretry backoff")
        assert all(item["path"] != str(both) for item in
                   (await searcher.search("code: retry backoff", legs=["words"]))["items"])
    finally:
        store.close()


async def test_code_only_index_and_meaning(repo, tmp_path):
    import numpy as np
    from omafindd.code import index_code
    from omafindd.search import Searcher

    tracked(repo, "retry.py", "# retry_with_backoff\n" + "\n" * 6 +
            "def retry_with_backoff():\n    pass\n")
    for n in range(25):
        tracked(repo, f"filler{n}.py", "unrelated filler")
    await index_code([repo], tmp_path / "index", FakeEmbedder())
    searcher = Searcher([], FakeEmbedder(), code_directory=tmp_path / "index", code_roots=[repo])
    result = await searcher.search("code: retry_with_backoff")
    assert result["items"][0]["name"] == "retry.py"
    assert result["items"][0]["open_line"] == 8
    assert (await searcher.search("code: retry backoff", legs=["meaning"]))["items"]
    assert np.isfinite(result["items"][0]["score"])


async def test_reindex_hook_and_settings_fallback(repo, tmp_path):
    from types import SimpleNamespace

    from omafindd.code import configured_roots
    from omafindd.indexing import reindex

    tracked(repo, "one.py", "def first(): pass")
    assert configured_roots(lambda: SimpleNamespace()) == ()
    roots = configured_roots(lambda: SimpleNamespace(code_roots=(str(repo),)))
    embedder = FakeEmbedder()
    await reindex([], directory=tmp_path / "data", embedder=embedder, code_roots=roots)
    assert (tmp_path / "data/index/code.sqlite").exists()
    assert embedder.mode is None


async def test_eval_threshold_and_code_database(repo, tmp_path, capsys):
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace

    from omafindd.code import index_code
    from omafindd.search import Searcher

    spec = importlib.util.spec_from_file_location("eval_run", Path("evals/run.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tracked(repo, "retry.py", "def retry_with_backoff(): pass")
    await index_code([repo], tmp_path / "index", FakeEmbedder())
    searcher = Searcher([], FakeEmbedder(), code_directory=tmp_path / "index", code_roots=[repo])
    queries = [{"q": "code: retry_with_backoff", "expect": ["repo/retry.py"],
                "tag": "code-lookup"}] * 9 + [
        {"q": "code: missing", "expect": ["missing.py"], "tag": "code-meaning"}]
    import asyncio

    assert await asyncio.wait_for(module.evaluate(searcher, queries, tmp_path, gate=0.9), 3)
    assert not await asyncio.wait_for(module.evaluate(searcher, queries, tmp_path, gate=0.91), 3)
    assert "first-hit total 9/10 (90.0%)" in capsys.readouterr().out
    config = tmp_path / "queries.json"
    config.write_text(json.dumps({"base": str(tmp_path), "manual": True, "queries": queries}))
    # The host-index path uses the same routing, without starting a real runtime in this test.
    module.Adapter = lambda runtime: FakeEmbedder()
    args = SimpleNamespace(index=tmp_path / "index", queries=config, gate=0.9)
    assert await asyncio.wait_for(module.run(args), 3) == 0


async def test_absent_code_index_does_not_start_embedder(tmp_path):
    from omafindd.search import Searcher

    class Unused(FakeEmbedder):
        async def start(self, mode):
            raise AssertionError("No code index should start a model")

    assert (await Searcher([], Unused()).search("code: retry"))["items"] == []


async def test_batches_precision_and_notebook_sources(repo, tmp_path):
    import sqlite3

    from omafindd.code import index_code
    from omafindd.search import Searcher

    class Bounded(FakeEmbedder):
        async def embed_documents(self, texts):
            assert len(texts) <= 16
            return await super().embed_documents(texts)

    notebook = {"cells": [
        {"source": "", "outputs": ["outputOnly"]},
        {"source": "def notebook_retry(): pass", "outputs": ["outputOnly"]},
    ]}
    tracked(repo, "demo.ipynb", json.dumps(notebook))
    long = tracked(repo, "long.py", "    statement()\n" * 4000)
    await index_code([repo], tmp_path / "index", Bounded())
    searcher = Searcher([], None, code_directory=tmp_path / "index", code_roots=[repo])
    assert (await searcher.search("code: outputOnly", legs=["words"]))["items"] == []
    result = await searcher.search("code: notebook_retry", legs=["words"])
    assert [(item["loc"], item["loc_end"], item["open_line"]) for item in result["items"]] == [
        (2, 2, None)
    ]
    with sqlite3.connect(tmp_path / "index/code.sqlite") as db:
        assert db.execute("SELECT max(length(excerpt)) FROM segments").fetchone()[0] <= 400
    long.unlink()
    await index_code([repo], tmp_path / "index", Bounded())
    with sqlite3.connect(tmp_path / "index/code.sqlite") as db:
        assert db.execute("SELECT count(*) FROM files").fetchone()[0] == 1

    class Invalid(FakeEmbedder):
        async def embed_documents(self, texts):
            return [vector * 0 for vector in await super().embed_documents(texts)]

    tracked(repo, "bad.py", "def bad_vector(): pass")
    await index_code([repo], tmp_path / "index", Invalid())
    with sqlite3.connect(tmp_path / "index/code.sqlite") as db:
        assert db.execute(
            "SELECT state,detail FROM files WHERE path LIKE '%/bad.py'"
        ).fetchone() == (
            "failed", "embedding precision fault"
        )
        assert db.execute("SELECT count(*) FROM segments JOIN files ON files.id=segments.file "
                          "WHERE path LIKE '%/bad.py'").fetchone()[0] == 0


async def test_service_routes_configured_code_roots(repo, tmp_path):
    from types import SimpleNamespace

    from omafindd.code import index_code
    from omafindd.service import SearchService
    from omafindd.state import State

    tracked(repo, "retry.py", "def retry_with_backoff(): pass")
    await index_code([repo], tmp_path / "index", FakeEmbedder())
    config = SimpleNamespace(roots=[], code_roots=(str(repo),), max_results=40, warm_minutes=5)
    service = SearchService(tmp_path / "index", lambda: config, FakeEmbedder(), State(),
                            volume_resolver=lambda path, **kwargs: ("v", tmp_path),
                            mounts_resolver=lambda: {})
    try:
        result = await service.handle({"t": "search", "seq": 3, "q": "code: retry_with_backoff",
                                       "legs": ["words"]})
        assert result["items"][0]["kind"] == "code"
        assert result["seq"] == 3
        config.code_roots = ()
        assert (await service.handle({"t": "search", "seq": 4, "q": "code: retry",
                                      "legs": ["words"]}))["items"] == []
    finally:
        await service.stop()


async def test_words_select_matching_stretch_and_meaning_respects_roots(repo, tmp_path):
    from omafindd.code import index_code
    from omafindd.search import Searcher

    tracked(repo, "late.py", "    unrelated()\n" * 200 + "def retry_with_backoff(): pass\n")
    other = tmp_path / "other"
    other.mkdir()
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    tracked(other, "outside.py", "def retry_with_backoff(): pass")
    await index_code([repo, other], tmp_path / "index", FakeEmbedder())
    searcher = Searcher([], FakeEmbedder(), code_directory=tmp_path / "index", code_roots=[repo])
    reply = await searcher.search("code: retry_with_backoff", legs=["words"])
    assert [item["name"] for item in reply["items"]] == ["late.py"]
    item = reply["items"][0]
    assert item["loc"] <= 201 <= item["loc_end"]
    assert item["open_line"] == 201
    result = await searcher.search("code: retry_with_backoff")
    assert result["items"][0]["path"].startswith(str(repo))


def test_reference_edge_cases_and_v3_notebook(tmp_path):
    from omafindd.code import check, lines, notebook_cells, read

    assert lines("\n\r\n") == []
    assert lines("  x\r\n  y\r\n")[0].last == 2
    assert len(lines("x" * 5000)[0].text) == 4000
    notebook = {"worksheets": [{"cells": [{"input": ["x\n"]}]}]}
    assert notebook_cells(json.dumps(notebook).encode()) == ["x\n"]
    for mark in ["DO NOT EDIT", "@generated", "Code generated by", "Autogenerated by",
                 "Generated by the protocol"]:
        with pytest.raises(ValueError, match="made by a program"):
            check(mark)
        check(mark, source=False)
    with pytest.raises(ValueError, match="private key"):
        check("PRIVATE KEY-----", source=False)
    path = tmp_path / "video.mts"
    data = bytearray(600)
    for offset in [4, 196, 388]:
        data[offset] = 0x47
    path.write_bytes(data)
    with pytest.raises(ValueError):
        read(path)


def test_cli_bootstrap_before_venv_has_no_third_party_imports(tmp_path):
    import os
    import sys

    result = subprocess.run(
        [sys.executable, "-S", "bin/omafind", "reindex", "--root", str(tmp_path)],
        env={**os.environ, "HOME": str(tmp_path)}, capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 1
    assert "venv missing" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr
