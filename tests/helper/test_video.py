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
    frames = extract_video(path)
    assert [s.kind for s in frames.segments] == ["frame"]
    assert frames.state == "partial"
    assert frames.info["audio_next"] == 0
    soundtrack = extract_video(path, frame_start=None)
    assert [s.kind for s in soundtrack.segments] == ["audio"]
    assert soundtrack.state == "done"
    assert [s.kind for s in extract_video(path, audio=False).segments] == ["frame"]


def test_keyframes_resume_at_next_kept_second(tmp_path):
    from itertools import islice

    from omafindd.extractors import keyframes

    path = video(tmp_path / "clip.mp4", shots=True)
    frames = keyframes(path)
    try:
        first = list(islice(frames, 2))
    finally:
        frames.close()
    assert [(piece.start, piece.end) for piece in first] == [(0.5, 3.5), (3.5, 6.5)]
    remaining = list(keyframes(path, start=first[-1].end))
    assert [(piece.start, piece.end) for piece in remaining] == [(6.5, 9.5), (9.5, 12)]
    assert first[0].thumbnail
    assert all(piece.thumbnail is None for piece in first[1:] + remaining)


@pytest.mark.parametrize("audio", [False, True])
async def test_long_video_commits_bounded_frame_passes_before_soundtrack(
    tmp_path, monkeypatch, audio
):
    import json
    import weakref
    from pathlib import Path

    from fakes.embedder import FakeEmbedder
    from omafindd import extractors, jobs
    from omafindd.crawler import crawl
    from omafindd.extractors import AudioPiece, ImagePart
    from omafindd.settings import Settings
    from omafindd.store import Store
    from support.media import InlinePool

    (tmp_path / "long.mp4").write_bytes(b"fixture")
    monkeypatch.setattr(jobs, "ProcessPoolExecutor", InlinePool)
    monkeypatch.setattr(extractors, "media_info", lambda path: {
        "duration": 1200, "streams": ["video", "audio"]
    })
    # Forty distinct shots, each with nine duplicate samples to skip.
    samples = [bytes([255] * 32 + [0] * 32), bytes([0] * 32 + [255] * 32)]

    def stream(argv, size):
        offset = round((float(argv[argv.index("-ss") + 1]) - 0.5) / 3)
        assert size == 64
        return (samples[(index // 10) % 2] for index in range(offset, 400))

    decoded = []

    def decode(argv):
        second = float(argv[argv.index("-ss") + 1])
        decoded.append(second)
        return str(second).encode()

    monkeypatch.setattr(extractors, "_stream", stream)
    monkeypatch.setattr(extractors, "_media_command", decode)
    monkeypatch.setattr(extractors, "_image", lambda path, budget, *, data:
                        ImagePart(data, 48, 48))
    monkeypatch.setattr(extractors, "_thumbnail", lambda path, *, data: b"jpeg:" + data)
    store = Store(tmp_path / "index/v.sqlite", volume="v", mount=tmp_path)
    audio_starts = []

    def windows(path, *, start):
        assert store.db.execute(
            "SELECT count(*) FROM segments WHERE kind='frame'"
        ).fetchone()[0] == 40
        audio_starts.append(start)
        return (AudioPiece(b"wav", second, min(second + 30, 1200))
                for second in range(int(start), 1200, 25))

    monkeypatch.setattr(extractors, "audio_windows", windows)
    extract = jobs.extract
    passes, images = [], []

    def bounded(*args):
        assert all(image() is None for image in images), "previous frame pass is still resident"
        result = extract(*args)
        frames = [s for s in result.segments if s.kind == "frame"]
        assert len(frames) <= 16
        assert len(result.segments) <= 16
        images.extend(weakref.ref(s.image) for s in frames)
        passes.append((len(frames), len(result.segments) - len(frames)))
        return result

    monkeypatch.setattr(jobs, "extract", bounded)
    try:
        crawl(store, [{"path": str(tmp_path)}])
        progress = []
        await jobs.Jobs(store, FakeEmbedder(), journal=tmp_path / "journal",
                        settings=Settings(audio=audio)).drain(progress=progress.append)
        assert passes == [(16, 0), (16, 0), (8, 0)] + ([(0, 16)] * 3 if audio else [])
        starts = [0.5 + 30 * index for index in range(40)]
        frames = store.db.execute(
            "SELECT loc,loc_end FROM segments WHERE kind='frame' ORDER BY loc"
        )
        assert [tuple(row) for row in frames] == list(zip(starts, starts[1:] + [1200], strict=True))
        assert decoded == starts
        assert audio_starts == ([0, 400, 800] if audio else [])
        row = store.db.execute("SELECT state,detail,info FROM files").fetchone()
        assert tuple(row[:2]) == ("done", None)
        info = json.loads(row["info"])
        assert Path(info["thumb"]).read_bytes() == b"jpeg:0.5"
        assert "frame_next" not in info and "audio_next" not in info
        assert [event["state"] for event in progress] == (
            ["partial"] * (len(passes) - 1) + ["done"]
        )
    finally:
        store.close()


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
            "failed" if frames_fail else "partial", "embedding-precision-fault",
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


def test_media_commands_name_a_missing_tool_and_keep_the_error_line():
    from omafindd.extractors import ExtractionError, _media_command, _stream

    script = "echo 'Warning: ignored' >&2; echo 'Error: bad header' >&2; exit 3"
    for call in (lambda argv: _media_command(argv), lambda argv: list(_stream(argv, 64))):
        with pytest.raises(ExtractionError) as missing:
            call(["omafind-no-such-tool"])
        assert (missing.value.code, missing.value.detail) == (
            "tool-missing", "omafind-no-such-tool")
        with pytest.raises(ExtractionError) as failed:
            call(["sh", "-c", script])
        assert (failed.value.code, failed.value.detail) == (
            "extract-failed", "sh failed: Error: bad header")
