import pytest
from support.media import video


@pytest.mark.parametrize("shots,expected", [(True, [0.5, 3.5, 6.5, 9.5]), (False, [0.5])])
def test_keyframes_keep_distinct_shots(tmp_path, shots, expected):
    from omafindd.extractors import keyframes

    pieces = list(keyframes(video(tmp_path / "clip.mp4", shots=shots)))
    assert [piece.start for piece in pieces] == expected
    assert [piece.end for piece in pieces] == expected[1:] + [12]
    assert all(max(piece.image.width, piece.image.height) <= 1024 for piece in pieces)


def test_sampling_interval_caps_long_video():
    from omafindd.extractors import sampling_interval

    assert sampling_interval(3000) == 3
    assert sampling_interval(6000) == 5
    assert len(range(0, 3000, int(sampling_interval(3000)))) <= 1200
    assert len(range(0, 6000, int(sampling_interval(6000)))) <= 1200


def test_video_without_soundtrack_has_no_windows(tmp_path):
    from omafindd.extractors import audio_windows, extract_video

    path = video(tmp_path / "clip.mp4")
    assert list(audio_windows(path)) == []
    result = extract_video(path)
    assert [s.kind for s in result.segments] == ["frame"]
    assert result.thumbnail


def test_video_audio_setting(tmp_path):
    from omafindd.extractors import extract_video

    path = video(tmp_path / "clip.mp4", audio=True)
    assert [s.kind for s in extract_video(path).segments] == ["frame", "audio"]
    assert [s.kind for s in extract_video(path, audio=False).segments] == ["frame"]


@pytest.mark.parametrize("frames_fail", [False, True])
async def test_media_precision_failure_preserves_only_valid_frames(
    tmp_path, monkeypatch, frames_fail
):
    import numpy as np
    from fakes.embedder import FakeEmbedder
    from omafindd import jobs
    from omafindd.crawler import crawl
    from omafindd.embedder import InputAudio
    from omafindd.store import Store
    from support.media import InlinePool

    video(tmp_path / "clip.mp4", audio=True)
    monkeypatch.setattr(jobs, "ProcessPoolExecutor", InlinePool)

    class InvalidAudio(FakeEmbedder):
        async def embed_documents(self, parts):
            if frames_fail or isinstance(parts[0], InputAudio):
                return [np.full(768, np.nan) for _ in parts]
            return await super().embed_documents(parts)

    store = Store(tmp_path / "index/v.sqlite", volume="v", mount=tmp_path)
    try:
        crawl(store, [{"path": str(tmp_path)}])
        runner = jobs.Jobs(store, InvalidAudio(), journal=tmp_path / "journal")
        await runner.drain()
        assert tuple(store.db.execute("SELECT state,detail FROM files").fetchone()) == (
            "failed" if frames_fail else "partial", "embedding precision fault",
        )
        for kind, count in (("frame", 0 if frames_fail else 1), ("audio", 0)):
            assert store.db.execute(
                "SELECT count(*) FROM segments WHERE kind=?", (kind,)
            ).fetchone()[0] == count
        await runner.drain(progress=lambda event: pytest.fail("partial video was requeued"))
    finally:
        store.close()


def test_average_hash_uses_integer_mean_and_strict_bits():
    from omafindd.extractors import average_hash

    assert average_hash(bytes([7] * 63 + [8])) == 1 << 63
    assert average_hash(bytes([7] * 64)) == 0


def test_hash_distance_four_is_dropped_five_is_kept(tmp_path, monkeypatch):
    from omafindd import extractors

    path = video(tmp_path / "clip.mp4")
    samples = [bytes(64), bytes([255] * 4 + [0] * 60), bytes([255] * 5 + [0] * 59)]
    monkeypatch.setattr(extractors, "_stream", lambda *args: (sample for sample in samples))
    pieces = list(extractors.keyframes(path))
    assert [piece.start for piece in pieces] == [0.5, 6.5]


def test_short_video_keeps_one_frame(tmp_path):
    from omafindd.extractors import keyframes
    from support.media import command

    path = tmp_path / "short.mp4"
    command("ffmpeg", "-v", "error", "-f", "lavfi", "-i",
            "color=black:s=160x90:r=2:d=1", "-threads", "1", "-c:v", "mpeg4", str(path))
    pieces = list(keyframes(path))
    assert [piece.start for piece in pieces] == [0.5]
