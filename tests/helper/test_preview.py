import json
import math
import shutil
import struct
import wave
from pathlib import Path

import pytest
from omafindd import preview


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("HOME", str(tmp_path))
    default = tmp_path / ".local/state/omarchy/defaults/editor"
    default.parent.mkdir(parents=True)
    default.write_text("/usr/bin/nvim --clean\nignored\n")
    return tmp_path


def test_docs_jump_and_rg_hits(environment):
    path = environment / "a.txt"
    lines = [f"line {i}" for i in range(1, 241)]
    lines[211] = "where they TALK"
    lines[214] = "another talk"
    path.write_text("\n".join(lines))
    reply = preview.render({"id": "docs", "kind": "text", "path": str(path),
                            "loc": 205, "loc_end": 222}, "tal")
    assert reply["jump"] == 212
    assert reply["range"] == [204, 220]
    assert [line["no"] for line in reply["lines"] if line["hit"]] == [212, 215]
    assert reply["editor"] == "nvim"
    assert reply["mode"] == "lines"


def test_empty_query_jumps_to_the_chunk_start(environment):
    path = environment / "a.txt"
    path.write_text("\n".join(["pass"] * 25))
    reply = preview.render({"id": "text", "kind": "text", "path": str(path), "loc": 20}, "")
    assert reply["jump"] == 20
    assert reply["range"] == [12, 25]
    assert not any(line["hit"] for line in reply["lines"])


def test_extracted_html_is_not_retained(environment):
    path = environment / "a.html"
    path.write_text("<p>first</p><p>target word</p><p>last</p>")
    reply = preview.render({"id": "html", "kind": "text", "path": str(path),
                            "loc": 1, "loc_end": 3, "info": {"extracted": True}}, "target")
    assert reply["jump"] == 2
    assert reply["lines"][1] == {"no": 2, "text": "target word", "hit": True}
    assert list((environment / "run/omafind/preview").iterdir()) == []


def test_extracted_line_spanning_chunks(environment):
    path = environment / "long.html"
    body = " ".join(f"word{i}" for i in range(1000))
    path.write_text(f"<p>first</p><p>{body}</p><p>last</p>")
    reply = preview.render({"id": "html", "kind": "text", "path": str(path),
                            "loc": 2, "info": {"extracted": True}}, "word900")
    assert reply["lines"][1]["text"] == body
    assert reply["lines"][1]["hit"]


def test_image_uses_thumb_even_offline(environment):
    assert preview.render({"id": "image", "kind": "image", "path": "/missing",
                           "offline": True, "thumb": "/cached.jpg"})["image"] == "/cached.jpg"


@pytest.mark.skipif(not shutil.which("pdftoppm"), reason="pdftoppm missing")
def test_pdf_page_render_and_cache(environment):
    path = environment / "a.pdf"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] >>"]
    data = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(data)
    data += b"xref\n0 4\n0000000000 65535 f \n"
    data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    data += f"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    path.write_bytes(data)
    item = {"id": "pdf", "kind": "pdf", "path": str(path), "loc": 1}
    reply = preview.render(item)
    image = Path(reply["image"])
    assert image.read_bytes().startswith(b"\x89PNG")
    signature = image.stat().st_mtime_ns
    assert preview.render(item)["image"] == str(image)
    assert image.stat().st_mtime_ns == signature
    assert reply["jump"] == 1


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg missing")
def test_audio_has_64_rms_bars(environment):
    path = environment / "a.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"".join(struct.pack("<h", int(16000 * math.sin(math.pi * i / 50)))
                                for i in range(8000)))
    reply = preview.render({"id": "audio", "kind": "audio", "path": str(path), "loc": .25})
    assert reply["mode"] == "bars"
    assert len(reply["bars"]) == 64
    assert all(type(bar) is int and 0 <= bar <= 100 for bar in reply["bars"])
    assert min(reply["bars"]) > 0


def test_video_frame_command_and_cache(environment, monkeypatch):
    import subprocess

    calls = []
    path = environment / "a.mp4"
    path.touch()

    def run(argv, **kwargs):
        assert kwargs["timeout"]
        calls.append(argv)
        Path(argv[-1]).write_bytes(b"frame")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(preview.subprocess, "run", run)
    item = {"id": "video", "kind": "video", "path": str(path), "loc": 872}
    legacy = preview.paths.preview_dir() / (preview._cache_key(path, 872, 1024) + ".jpg")
    legacy.write_bytes(b"old frame")
    reply = preview.render(item)
    assert reply["jump"] == 872
    assert Path(reply["image"]) != legacy
    assert Path(reply["image"]).read_bytes() == b"frame"
    preview.render(item)
    assert len(calls) == 1
    assert calls[0][:5] == ["ffmpeg", "-v", "error", "-ss", "872"]
    assert calls[0][calls[0].index("-vf") + 1] == "scale='min(1024,iw)':-2"
    assert calls[0][calls[0].index("-q:v"):calls[0].index("-q:v") + 2] == ["-q:v", "2"]
    assert "-y" in calls[0]


@pytest.mark.parametrize("value,expected", [("SUPER + D", "SUPER + D"),
                                              ("SUPER + CTRL + E", "SUPER + CTRL + E"),
                                              ("super + E", "SUPER + E"),
                                              ("SUPER", "SUPER + E"),
                                              ("SUPER + SUPER + E", "SUPER + E"),
                                              (42, "SUPER + E")])
def test_shortcut_setting(environment, value, expected):
    from omafindd.settings import load

    path = environment / "shell.json"
    path.write_text(json.dumps({"plugins": [{"id": "radimsem.omafind", "shortcut": value}]}))
    assert load(path).shortcut == expected


@pytest.mark.parametrize("kind", ["pdf", "video"])
def test_failed_concurrent_render_preserves_finished_image(environment, monkeypatch, kind):
    path = environment / "source"
    path.touch()
    jump = 1
    key = preview._cache_key(path, jump, preview.RENDER_SIDE if kind == "pdf" else "1024q2")
    image = preview.paths.preview_dir() / (key + (".png" if kind == "pdf" else ".jpg"))
    outputs = []

    def run(argv):
        output = Path(argv[-1] + ".png") if kind == "pdf" else Path(argv[-1])
        outputs.append(output)
        output.write_bytes(b"unfinished")
        image.write_bytes(b"finished by another render")
        raise preview.ExtractionError("failed")

    monkeypatch.setattr(preview, "_run", run)
    with pytest.raises(preview.ExtractionError):
        preview.render({"id": kind, "kind": kind, "path": str(path), "loc": jump})
    assert image.read_bytes() == b"finished by another render"
    assert outputs[0] != image
    assert list(image.parent.iterdir()) == [image]


def test_audio_decodes_low_rate_and_caches_by_mtime(environment, monkeypatch):
    import subprocess

    path = environment / "audio.wav"
    path.touch()
    calls = []
    popen = subprocess.Popen
    monkeypatch.setattr(preview, "_run", lambda argv: b"1")

    def decode(argv, **kwargs):
        calls.append(argv)
        return popen(["head", "-c", "800", "/dev/zero"], **kwargs)

    monkeypatch.setattr(preview.subprocess, "Popen", decode)
    first = preview._bars(path)
    first[0] = 99
    assert preview._bars(path) == [0] * 64
    assert len(calls) == 1
    assert calls[0][calls[0].index("-ar") + 1] == "400"
    import os

    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1))
    preview._bars(path)
    assert len(calls) == 2


def test_online_image_previews_the_original(environment):
    path = environment / "photo.png"
    path.write_bytes(b"png")
    reply = preview.render({"id": "image", "kind": "image", "path": str(path),
                            "thumb": "/cached.jpg"})
    assert reply["image"] == str(path)


def test_heic_gets_one_cached_render_at_twice_the_box(environment, monkeypatch):
    path = environment / "photo.HEIC"
    path.write_bytes(b"heic")
    calls = []

    def run(argv):
        calls.append(argv)
        Path(argv[-1]).write_bytes(b"jpeg")

    monkeypatch.setattr(preview, "_run", run)
    item = {"id": "image", "kind": "image", "path": str(path), "thumb": "/cached.jpg"}
    first = preview.render(item)["image"]
    assert preview.render(item)["image"] == first
    assert len(calls) == 1
    assert calls[0][:5] == ["magick", f"{path}[0]", "-auto-orient", "-resize", "1200x840>"]
    assert first.endswith(".jpg") and Path(first).read_bytes() == b"jpeg"


def test_pdf_page_renders_at_render_side(environment, monkeypatch):
    path = environment / "a.pdf"
    path.write_bytes(b"%PDF")
    calls = []

    def run(argv):
        calls.append(argv)
        Path(argv[-1] + ".png").write_bytes(b"png")

    monkeypatch.setattr(preview, "_run", run)
    preview.render({"id": "pdf", "kind": "pdf", "path": str(path), "loc": 3})
    assert calls[0][calls[0].index("-scale-to") + 1] == "1200"
