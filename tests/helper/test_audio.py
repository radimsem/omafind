import base64
import json
from pathlib import Path

import pytest
from fakes.embedder import FakeEmbedder
from support.media import InlinePool, tone


@pytest.mark.parametrize("seconds,expected", [
    (70, [(0, 30), (25, 55), (50, 70)]), (31, [(0, 30)]), (2, [(0, 2)]), (1, []),
])
def test_audio_windows(tmp_path, seconds, expected):
    from omafindd.extractors import audio_windows

    pieces = list(audio_windows(tone(tmp_path / "tone.wav", seconds)))
    assert [(piece.start, piece.end) for piece in pieces] == expected
    assert all(piece.wav.startswith(b"RIFF") for piece in pieces)


@pytest.mark.parametrize("off", [False, True])
async def test_silence_and_disabled_audio_are_skipped(tmp_path, monkeypatch, off):
    from omafindd import jobs
    from omafindd.crawler import crawl
    from omafindd.settings import Settings
    from omafindd.store import Store

    tone(tmp_path / "sound.mp3", 3, silent=not off)
    monkeypatch.setattr(jobs, "ProcessPoolExecutor", InlinePool)
    with_store = Store(tmp_path / "index/v.sqlite", volume="v", mount=tmp_path)
    try:
        crawl(with_store, [{"path": str(tmp_path)}])
        embedder = FakeEmbedder()
        await jobs.Jobs(with_store, embedder, journal=tmp_path / "journal",
                        settings=Settings(audio=not off)).drain()
        row = with_store.db.execute("SELECT state,detail FROM files").fetchone()
        assert tuple(row) == ("skipped", "audio search is off" if off else "silent audio")
        assert embedder.mode is None
    finally:
        with_store.close()


def test_reference_audio_content_part():
    from omafindd.embedder import InputAudio, build_request

    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    data = base64.b64encode((fixtures / "reference/speech.wav").read_bytes()).decode()
    expected = json.loads((fixtures / "audio_part.json").read_text())
    assert build_request([InputAudio(data)])["input"][0]["content"][0] == expected


async def test_adapter_audio_is_unprefixed():
    from omafindd.embedder import InputAudio
    from omafindd.embedding import Adapter

    received = []

    class Runtime(FakeEmbedder):
        async def embed(self, parts):
            received.extend(parts)
            return await super().embed(parts)

    await Adapter(Runtime()).embed_documents([InputAudio("YWJj")])
    assert received == [InputAudio("YWJj")]


def test_long_audio_extraction_returns_bounded_windows(tmp_path):
    from omafindd.extractors import extract_audio

    path = tone(tmp_path / "long.wav", 410)
    first = extract_audio(path)
    assert len(first.segments) == 16
    assert first.state == "partial"
    assert first.info["audio_next"] == 400
    final = extract_audio(path, start=first.info["audio_next"])
    assert [(s.loc, s.loc_end) for s in final.segments] == [(400, 410)]
    assert final.state == "done"


async def test_audio_jobs_resume_batches_without_losing_windows(tmp_path, monkeypatch):
    from omafindd import jobs
    from omafindd.crawler import crawl
    from omafindd.settings import Settings
    from omafindd.store import Store

    tone(tmp_path / "long.wav", 410)
    monkeypatch.setattr(jobs, "ProcessPoolExecutor", InlinePool)
    received = []

    class Recording(FakeEmbedder):
        async def embed_documents(self, parts):
            from omafindd.embedder import InputAudio
            assert all(isinstance(part, InputAudio) for part in parts)
            received.append(len(parts))
            return await super().embed_documents(parts)

    store = Store(tmp_path / "index/v.sqlite", volume="v", mount=tmp_path)
    try:
        crawl(store, [{"path": str(tmp_path)}])
        await jobs.Jobs(store, Recording(), journal=tmp_path / "journal",
                        settings=Settings()).drain()
        assert received == [16, 1]
        assert [r[0] for r in store.db.execute(
            "SELECT loc FROM segments WHERE kind='audio' ORDER BY loc"
        )] == list(range(0, 401, 25))
        assert store.db.execute("SELECT state FROM files").fetchone()[0] == "done"
    finally:
        store.close()
