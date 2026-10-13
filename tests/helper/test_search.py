import numpy as np
import pytest
from fakes.embedder import FakeEmbedder
from omafindd.crawler import crawl
from omafindd.extractors import Segment
from omafindd.store import Store


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "index/v.sqlite", volume="v", mount=tmp_path)
    yield value
    value.close()


async def add(store, path, text, kind="text", loc=1, vector=None):
    path.write_text(text)
    crawl(store, [{"path": str(path.parent), "excludes": []}])
    file = store.db.execute(
        "SELECT id FROM files WHERE path=?", (path.relative_to(store.mount).as_posix(),)
    ).fetchone()[0]
    vectors = [vector] if vector is not None else await FakeEmbedder().embed_documents([text])
    store.write(
        file,
        [Segment("page" if kind == "pdf" else "chunk", "text", text, loc=loc)],
        vectors,
        state="done",
        info={},
    )
    return file


def test_modality_centering_small_groups_and_deviation_floor():
    from omafindd.search import meaning

    scores = np.array([0.2] * 20 + [0.6] * 20 + [0.5])
    modalities = ["text"] * 20 + ["image"] * 20 + ["audio"]
    result = meaning(scores, modalities)
    assert result[0] == pytest.approx(result[20])
    assert result[-1] > result[0]
    assert np.isfinite(meaning(np.ones(20), ["text"] * 20)).all()
    assert np.array_equal(meaning(np.ones(20), ["text"] * 20), np.zeros(20))


def test_lookup_and_regular_fusion_weights():
    from omafindd.search import fused_score, is_lookup

    assert fused_score(3, 1, lookup=False, hinted=False) == 5
    assert fused_score(3, 1, lookup=True, hinted=True) == 6.5
    assert is_lookup("K7Q2LM")
    assert is_lookup("4412")
    assert is_lookup('"invoice due"')
    assert not is_lookup("lunar eclipse")


async def test_fusion_order_and_jump_to_keyword_page(store, tmp_path):
    from omafindd.search import Searcher

    await add(store, tmp_path / "invoice.pdf", "invoice 4412 payment", kind="pdf", loc=12)
    await add(store, tmp_path / "notes.txt", "invoice discussion")
    result = await Searcher([store], FakeEmbedder()).search("invoice 4412")
    assert [item["name"] for item in result["items"]] == ["invoice.pdf", "notes.txt"]
    assert result["items"][0]["loc"] == 12
    assert result["items"][0]["hits"] == ["invoice", "4412"]
    assert any(part["m"] for part in result["items"][0]["snippet"])


async def test_z_gate_rejects_common_cosines(store, tmp_path):
    from omafindd.search import Searcher

    await add(store, tmp_path / "one.txt", "lunar eclipse")
    result = await Searcher([store], FakeEmbedder()).search("unrelated")
    assert result["items"] == []


async def test_meaning_only_z_gate_and_weak_flag(store, tmp_path):
    from omafindd.search import Searcher

    query = await FakeEmbedder().embed_query("telescope")
    await add(store, tmp_path / "best.txt", "telescope", vector=query)
    for n in range(25):
        await add(store, tmp_path / f"other{n}.txt", "unrelated", vector=np.eye(1, 768, 100)[0])
    await add(store, tmp_path / "weak.txt", "telescope reflection", vector=np.eye(1, 768, 100)[0])
    result = await Searcher([store], FakeEmbedder()).search("telescope")
    assert result["items"][0]["name"] == "best.txt"
    assert result["items"][-1]["weak"] is True
    assert result["weaker"] == 1
    assert [p["score"] for p in result["items"]] == sorted(
        [p["score"] for p in result["items"]], reverse=True
    )


@pytest.mark.parametrize(
    "prefix,names",
    [
        ("doc:", ["notes.txt"]),
        ("pdf:", ["a.pdf"]),
        ("img:", []),
        ("vid:", []),
        ("aud:", []),
        ("code:", []),
    ],
)
async def test_all_prefixes_filter(store, tmp_path, prefix, names):
    from omafindd.search import Searcher

    await add(store, tmp_path / "notes.txt", "fixture content")
    await add(store, tmp_path / "a.pdf", "fixture content", kind="pdf")
    result = await Searcher([store], FakeEmbedder()).search(prefix + "fixture")
    assert [item["name"] for item in result["items"]] == names


async def test_external_reindex_reloads_matrix(store, tmp_path):
    from omafindd.search import Searcher

    searcher = Searcher([store], FakeEmbedder())
    await add(store, tmp_path / "a.txt", "lunar eclipse")
    assert (await searcher.search("lunar"))["items"][0]["name"] == "a.txt"
    other = Store(store.path, volume="v", mount=tmp_path)
    await add(other, tmp_path / "b.txt", "sourdough flour")
    assert (await searcher.search("sourdough"))["items"][0]["name"] == "b.txt"
    assert searcher.matrix.dtype == np.float32
    other.close()


async def test_missing_embedder_degrades_to_words(store, tmp_path):
    from omafindd.search import Searcher

    await add(store, tmp_path / "a.txt", "lunar eclipse")
    result = await Searcher([store], None).search("lunar")
    assert result["items"][0]["leg"] == "words"
    assert result["degraded"]


def test_search_text_normalizes_joiners_arabic_and_ligatures():
    from omafindd.search_text import normalized

    assert normalized("Ａ ﬁ أَ\u200d\u200b") == "A fi ا "


def test_terms_keep_indic_vowel_marks():
    from omafindd.search_text import terms

    assert terms("কুমিরও") == ["কুমিরও"]


async def test_words_budget_counts_files_instead_of_segments(store, tmp_path):
    from omafindd.search import Searcher

    file = await add(store, tmp_path / "long.pdf", "needle", kind="pdf")
    segment = Segment("page", "text", "needle", loc=1)
    store.write(
        file, [segment] * 1001, [np.eye(1, 768)[0]] * 1001, state="done", info={"pages": 1001}
    )
    await add(store, tmp_path / "short.txt", "a needle among other words")
    result = await Searcher([store], FakeEmbedder()).search("needle", legs=["words"])
    assert {item["name"] for item in result["items"]} == {"long.pdf", "short.txt"}


async def test_search_keeps_one_snapshot_during_cli_commit(store, tmp_path, monkeypatch):
    from omafindd.search import Searcher

    other = Store(store.path, volume="v", mount=tmp_path)
    searcher = Searcher([store], FakeEmbedder())
    words = searcher._words
    committed = False

    async def commit_before_words(*args):
        nonlocal committed
        if not committed:
            await add(other, tmp_path / "new.txt", "lunar eclipse")
            committed = True
        return await words(*args)

    monkeypatch.setattr(searcher, "_words", commit_before_words)
    first = await searcher.search("lunar", legs=["words"])
    assert first["items"] == []
    second = await searcher.search("lunar", legs=["words"])
    assert second["items"][0]["name"] == "new.txt"
    other.close()


async def test_vector_cache_keeps_only_arrays_and_fetches_returned_metadata(store, tmp_path):
    from omafindd.search import Searcher

    for n in range(3):
        await add(store, tmp_path / f"note{n}.txt", "lunar eclipse")
    searcher = Searcher([store], FakeEmbedder())
    statements = []
    store.db.set_trace_callback(statements.append)
    searcher.reload()
    assert not any("SELECT *" in sql or "excerpt" in sql for sql in statements)
    assert all(isinstance(column, np.ndarray) for column in searcher.columns.values())
    assert {"id", "file", "modality", "loc", "loc_end", "kind"} <= searcher.columns.keys()
    assert not {"excerpt", "vec"} & searcher.columns.keys()
    assert searcher.matrix.shape == (3, 768)
    assert searcher.matrix.dtype == np.float32
    statements.clear()
    reply = await searcher.search("lunar", legs=["words"], limit=1)
    assert len(reply["items"]) == 1 and reply["items"][0]["snippet"]
    assert sum("SELECT * FROM files" in sql for sql in statements) == 1
    assert all("WHERE id=" in sql for sql in statements if "SELECT * FROM files" in sql)


async def test_vector_cache_appends_without_rereading_existing_vectors(store, tmp_path):
    from omafindd.search import Searcher

    await add(store, tmp_path / "one.txt", "lunar eclipse")
    searcher = Searcher([store], FakeEmbedder())
    searcher.reload()
    before = searcher.matrix.copy()
    last = store.db.execute("SELECT max(id) FROM segments WHERE vec IS NOT NULL").fetchone()[0]
    other = Store(store.path, volume="v", mount=tmp_path)
    try:
        await add(other, tmp_path / "two.txt", "sourdough")
        statements = []
        store.db.set_trace_callback(statements.append)
        searcher.reload()
        assert searcher.matrix.shape == (2, 768)
        assert np.array_equal(searcher.matrix[:1], before)
        loads = [sql for sql in statements if "s.vec" in sql]
        assert len(loads) == 1 and f"s.id>{last}" in loads[0]
        matrix = searcher.matrix
        with other.db:
            other.db.execute("UPDATE files SET mtime=mtime+1")
        statements.clear()
        searcher.reload()
        assert searcher.matrix is matrix
        assert not any("s.vec" in sql for sql in statements)
    finally:
        other.close()


async def test_vector_cache_reloads_replacement_even_when_ids_are_reused(store, tmp_path):
    from omafindd.search import Searcher

    file = await add(store, tmp_path / "one.txt", "lunar eclipse")
    searcher = Searcher([store], FakeEmbedder())
    searcher.reload()
    old_id = store.db.execute("SELECT max(id) FROM segments").fetchone()[0]
    other = Store(store.path, volume="v", mount=tmp_path)
    try:
        vector = np.eye(1, 768, 300)[0]
        other.write(file, [Segment("chunk", "text", "sourdough")], [vector], state="done", info={})
        assert other.db.execute("SELECT max(id) FROM segments").fetchone()[0] == old_id
        searcher.reload()
        assert np.array_equal(searcher.matrix[0], vector.astype(np.float32))
        with other.db:
            other.delete(file)
        searcher.reload()
        assert searcher.matrix.shape == (0, 768)
    finally:
        other.close()


@pytest.mark.parametrize("query,legs,embedder", [
    ("lunar", ["words"], FakeEmbedder()),
    ("lunar", ["words", "meaning"], None),
    ("code:lunar", ["words", "meaning"], FakeEmbedder()),
    ("", ["words", "meaning"], FakeEmbedder()),
])
async def test_search_without_meaning_does_not_load_vectors(store, tmp_path, query, legs, embedder):
    from omafindd.search import Searcher

    await add(store, tmp_path / "one.txt", "lunar eclipse")
    searcher = Searcher([store], embedder)
    statements = []
    store.db.set_trace_callback(statements.append)
    await searcher.search(query, legs=legs)
    assert not any("s.vec" in sql or "count(*)" in sql for sql in statements)
    assert searcher.matrix.shape == (0, 768)


async def test_full_reload_releases_old_matrix_and_fills_preallocated_rows(
    store, tmp_path, monkeypatch
):
    import weakref

    from omafindd.search import Searcher

    file = await add(store, tmp_path / "one.txt", "lunar eclipse")
    searcher = Searcher([store], FakeEmbedder())
    searcher.reload()
    old = weakref.ref(searcher.matrix)
    vector = np.eye(1, 768, 300)[0]
    store.write(file, [Segment("chunk", "text", "sourdough")], [vector], state="done", info={})
    with store.db:
        store.db.execute(
            "INSERT INTO segments(file,kind,modality,vec) VALUES(?,'chunk','text',?)",
            (file, b"invalid!"),
        )
    empty, asarray = np.empty, np.asarray
    allocated = []

    def allocate(shape, *args, **kwargs):
        if shape == (2, 768):
            assert old() is None, "old matrix remains resident during a full reload"
            allocated.append(shape)
        return empty(shape, *args, **kwargs)

    def convert(values, *args, **kwargs):
        assert not (isinstance(values, list) and any(isinstance(v, np.ndarray) for v in values)), (
            "reload retained an intermediate list of vectors"
        )
        return asarray(values, *args, **kwargs)

    monkeypatch.setattr(np, "empty", allocate)
    monkeypatch.setattr(np, "asarray", convert)
    searcher.reload()
    assert allocated == [(2, 768)]
    assert searcher.matrix.shape == (1, 768)
    assert np.array_equal(searcher.matrix[0], vector.astype(np.float32))


@pytest.mark.parametrize("prefix,expected", [
    ("", [("v", 2), ("w", 12)]), ("doc:", [("v", 2)]), ("pdf:", [("w", 12)])
])
async def test_meaning_reduces_segments_per_file_in_numpy(store, tmp_path, prefix, expected):
    from omafindd.search import Searcher

    query = await FakeEmbedder().embed_query("telescope")
    neutral = np.roll(query, 1)
    file = await add(store, tmp_path / "best.txt", "fixture", vector=query)
    store.write(file, [Segment("chunk", "text", "fixture", loc=loc) for loc in [1, 2, 3]],
                [neutral, query, query], state="done", info={})
    filler = await add(store, tmp_path / "other.txt", "fixture", vector=neutral)
    store.write(filler, [Segment("chunk", "text", "fixture")] * 100,
                [neutral] * 100, state="done", info={})
    other = Store(tmp_path / "index/w.sqlite", volume="w", mount=tmp_path)
    await add(other, tmp_path / "other.pdf", "fixture", kind="pdf", loc=12, vector=query)
    searcher = Searcher([store, other], FakeEmbedder())
    searcher.reload()
    accesses = []

    class Column(np.ndarray):
        def __getitem__(self, index):
            if isinstance(index, (int, np.integer)):
                accesses.append(index)
            return super().__getitem__(index)

    for name in ("volume", "file"):
        searcher.columns[name] = searcher.columns[name].view(Column)

    class Modality(str):
        def __hash__(self):
            raise AssertionError("meaning search hashed modalities once per segment")

    searcher.columns["modality"] = np.array(
        [Modality(value) for value in searcher.columns["modality"]], dtype=object
    )
    try:
        reply = await searcher.search(prefix + "telescope", legs=["meaning"])
        assert [(item["volume"], item["loc"]) for item in reply["items"]] == expected
        assert len(accesses) <= 6, "meaning search accessed file metadata once per segment"
    finally:
        other.close()


@pytest.mark.parametrize("kinds,names,total", [
    (["pdf"], ["a.pdf"], 2), (["text", "pdf"], ["best.txt"], 3), ([], [], 0),
])
async def test_kinds_filter_before_limit_and_counts(store, tmp_path, kinds, names, total):
    from omafindd.search import Searcher

    await add(store, tmp_path / "best.txt", "needle haystack")
    await add(store, tmp_path / "a.pdf", "needle", kind="pdf")
    await add(store, tmp_path / "b.pdf", "needle", kind="pdf")
    reply = await Searcher([store], None).search("needle haystack", legs=["words"],
                                               kinds=kinds, limit=1)
    assert [item["name"] for item in reply["items"]] == names
    assert reply["total"] == total
    assert reply["weaker"] == 0


async def test_kinds_route_code_index_without_content_index(tmp_path, monkeypatch):
    from omafindd import search_code
    from omafindd.search import Searcher

    calls = []

    async def code(searcher, q, **kwargs):
        calls.append((q, kwargs))
        return {"t": "results", "seq": kwargs["seq"], "items": [], "total": 0,
                "weaker": 0, "degraded": None, "legs": kwargs["legs"], "ms": {}}

    monkeypatch.setattr(search_code, "search_code", code)
    await Searcher([], None).search("needle", kinds=["code"], legs=["words"])
    assert calls[0][0] == "needle"


async def test_kinds_filter_before_keyword_candidate_budget(store, tmp_path):
    from omafindd.search import Searcher

    for i in range(101):
        await add(store, tmp_path / f"note{i}.txt", "needle")
    await add(store, tmp_path / "wanted.pdf", "needle", kind="pdf")
    reply = await Searcher([store], None).search("needle", kinds=["pdf"], legs=["words"])
    assert [item["name"] for item in reply["items"]] == ["wanted.pdf"]
    assert reply["total"] == 1


async def test_mixed_code_kinds_merge_before_global_limit(store, tmp_path, monkeypatch):
    from omafindd import search_code
    from omafindd.search import Searcher

    await add(store, tmp_path / "note.txt", "needle")

    async def code(searcher, q, **kwargs):
        return {"t": "results", "seq": kwargs["seq"], "legs": list(kwargs["legs"]),
                "items": [{"id": "code:1", "kind": "code", "score": 10, "weak": False}],
                "total": 1, "weaker": 0, "degraded": None,
                "ms": {"embed": 0, "scan": 0, "words": 0, "total": 0}}

    monkeypatch.setattr(search_code, "search_code", code)
    searcher = Searcher([store], None)
    reply = await searcher.search("needle", kinds=["text", "code"], legs=["words"], limit=2)
    assert [item["kind"] for item in reply["items"]] == ["code", "text"]
    assert reply["total"] == 2
    assert reply["weaker"] == 1
    limited = await searcher.search("needle", kinds=["text", "code"], legs=["words"], limit=1)
    assert limited["total"] == 2
    assert len(limited["items"]) == 1
    assert limited["weaker"] == 0
    narrowed = await searcher.search("doc:needle", kinds=["code", "text"], legs=["words"])
    assert [item["kind"] for item in narrowed["items"]] == ["text"]
