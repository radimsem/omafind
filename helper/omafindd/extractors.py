import bisect
import html
import io
import json
import math
import re
import subprocess
import tempfile
import wave
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from xml.etree import ElementTree

import numpy as np

from .rules import screenshot_like


class ExtractionError(Exception):
    pass


@dataclass(frozen=True)
class ImagePart:
    data: bytes
    width: int
    height: int


@dataclass(frozen=True)
class Segment:
    kind: str
    modality: str
    text: str = ""
    loc: float | None = None
    loc_end: float | None = None
    image: ImagePart | None = None
    audio: bytes | None = None


@dataclass
class Extracted:
    segments: list[Segment]
    info: dict = field(default_factory=dict)
    state: str = "done"
    thumbnail: bytes | None = None
    ocr_text: str = ""
    detail: str | None = None


# embeddinggemma reads at most 2,048 tokens per input, prefix included. Its tokenizer falls
# back to single bytes, so a token always covers at least one UTF-8 byte.
TOKEN_CAP = 1800


def estimated_tokens(text: str) -> int:
    return len(text.encode())


def chunks(text: str) -> list[Segment]:
    newlines = [i for i, character in enumerate(text) if character == "\n"]
    result = []
    start = 0
    while start < len(text) and len(result) < 5000:
        end = min(start + 1800, len(text))
        if end < len(text):
            space = next((i for i in range(end - 1, start + 900, -1) if text[i].isspace()), None)
            if space is not None:
                end = space
        while end - start > 1 and estimated_tokens(text[start:end]) > TOKEN_CAP:
            end = start + (end - start) * 3 // 4
        left, right = start, end
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        if left < right:
            result.append(
                Segment(
                    "chunk",
                    "text",
                    text[left:right],
                    bisect.bisect_left(newlines, left) + 1,
                    bisect.bisect_left(newlines, right) + 1,
                )
            )
        if end == len(text):
            break
        next_start = max(start + 1, end - 200)
        while next_start < end and not text[next_start].isspace():
            next_start += 1
        start = next_start
    return result


def plain_text_html(text: str) -> str:
    for pattern in (
        r"(?is)<script\b.*?</script\s*>",
        r"(?is)<style\b.*?</style\s*>",
        r"(?s)<!--.*?-->",
        r"(?is)<head\b.*?</head\s*>",
    ):
        text = re.sub(pattern, " ", text)
    text = re.sub(r"(?i)<(br|/p|/div|/li|/h[1-6]|/tr|/section|/article)\b[^>]*>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def extract_text(path: Path) -> Extracted:
    extension = path.suffix.lower()
    if extension in (".docx", ".odt"):
        member = "word/document.xml" if extension == ".docx" else "content.xml"
        try:
            with zipfile.ZipFile(path) as archive:
                tree = ElementTree.fromstring(archive.read(member))
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as error:
            raise ExtractionError("unreadable Office file") from error
        paragraphs = [
            "".join(node.itertext())
            for node in tree.iter()
            if node.tag.rsplit("}", 1)[-1] in ("p", "h")
        ]
        text = "\n".join(paragraphs)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
        if extension == ".html":
            text = plain_text_html(text)
    info = {"extracted": True} if extension in (".html", ".docx", ".odt") else {}
    return Extracted(chunks(text), info)


def target_size(width: int, height: int, budget: int) -> tuple[int, int]:
    factor = math.sqrt(budget * 2304 / (width * height))
    w, h = int(factor * width / 48) * 48, int(factor * height / 48) * 48
    if w == 0:
        w, h = 48, min(max(48, height // width * 48), budget * 48)
    elif h == 0:
        h, w = 48, min(max(48, width // height * 48), budget * 48)
    return w, h


def _pdf_command(argv, *, text=True):
    try:
        result = subprocess.run(argv, capture_output=True, text=text, timeout=60)
    except subprocess.TimeoutExpired as error:
        raise ExtractionError("timeout") from error
    if result.returncode:
        detail = result.stderr if text else result.stderr.decode(errors="replace")
        raise ExtractionError(
            "encrypted-pdf" if "Incorrect password" in detail else f"{argv[0]} failed"
        )
    return result.stdout


def extract_pdf(path: Path, start: int = 1) -> Extracted:
    info = _pdf_command(["pdfinfo", str(path)])
    match = re.search(r"(?m)^Pages:\s+(\d+)", info)
    if match is None:
        raise ExtractionError("pdfinfo returned no page count")
    pages = int(match[1])
    end = min(pages, 5000, (30 if start == 1 else start + 31) if pages > 50 else pages)
    if start > end:
        return Extracted([], {"pages": pages, "read_to": end})
    text = _pdf_command(
        ["pdftotext", "-f", str(start), "-l", str(end), "-enc", "UTF-8", str(path), "-"]
    )
    texts = text.split("\f")
    if texts and not texts[-1].strip():
        texts.pop()
    if len(texts) != end - start + 1:
        raise ExtractionError("pdftotext returned an unexpected page count")
    segments = []
    with tempfile.TemporaryDirectory(prefix="omafind-pdf-") as directory:
        for page, body in enumerate(texts, start):
            body = body.strip()
            if len(body) >= 200:
                for piece in chunks(body):
                    segments.append(Segment("page", "text", piece.text, loc=page, loc_end=page))
                continue
            prefix = Path(directory) / "page"
            _pdf_command(
                [
                    "pdftoppm",
                    "-f",
                    str(page),
                    "-l",
                    str(page),
                    "-scale-to",
                    "1024",
                    "-singlefile",
                    "-png",
                    str(path),
                    str(prefix),
                ]
            )
            image = prefix.with_suffix(".png")
            width, height = map(
                int, _pdf_command(["magick", "identify", "-format", "%w %h", str(image)]).split()
            )
            width, height = target_size(width, height, 280)
            data = _pdf_command(
                [
                    "magick",
                    str(image),
                    "-filter",
                    "Catrom",
                    "-resize",
                    f"{width}x{height}!",
                    "png:-",
                ],
                text=False,
            )
            segments.append(
                Segment("page_image", "image", body, loc=page, image=ImagePart(data, width, height))
            )
    return Extracted(
        segments, {"pages": pages, "read_to": end}, "partial" if end < min(pages, 5000) else "done"
    )


def _image(source: str, budget: int, *, data=None) -> ImagePart:
    dimensions = _media_command(
        ["magick", source, "-auto-orient", "-format", "%w %h", "info:"], data=data
    )
    width, height = target_size(*map(int, dimensions.split()), budget)
    resized = _media_command(
        ["magick", source, "-auto-orient", "-filter", "Catrom", "-resize",
         f"{width}x{height}!", "png:-"], data=data
    )
    return ImagePart(resized, width, height)


def _thumbnail(source: str, *, data=None) -> bytes:
    return _media_command(
        ["magick", source, "-auto-orient", "-thumbnail", "128x128", "jpg:-"], data=data
    )


def _media_command(argv, *, data=None) -> bytes:
    try:
        result = subprocess.run(argv, input=data, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired as error:
        raise ExtractionError("timeout") from error
    if result.returncode:
        raise ExtractionError(f"{argv[0]} failed")
    return result.stdout


def extract_image(path: Path, *, image_budget=140) -> Extracted:
    source = str(path) + "[0]"
    width, height = map(int, _media_command(
        ["magick", source, "-auto-orient", "-format", "%w %h", "info:"]
    ).split())
    screenshot = screenshot_like(path.name, width, height)
    image = _image(source, 280 if screenshot else image_budget)
    text = ""
    if screenshot:
        original = _media_command(["magick", source, "-auto-orient", "png:-"])
        text = _media_command(["tesseract", "stdin", "stdout", "-l", "eng"],
                              data=original).decode().strip()
    return Extracted(
        [Segment("image", "image", image=image)], {"width": width, "height": height},
        thumbnail=_thumbnail(source), ocr_text=text,
    )


def media_info(path: Path) -> dict:
    info = json.loads(_media_command([
        "ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
        "-of", "json", str(path),
    ]))
    duration = float(info.get("format", {}).get("duration", 0))
    return {"duration": duration if math.isfinite(duration) and duration > 0 else 0,
            "streams": {stream["codec_type"] for stream in info.get("streams", [])}}


def _stream(argv, size: int) -> Iterator[bytes]:
    # A file for stderr prevents pipe deadlock while stdout is consumed incrementally.
    with tempfile.TemporaryFile() as errors:
        with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=errors) as process:
            try:
                while block := process.stdout.read(size):
                    yield block
                if process.wait():
                    raise ExtractionError(f"{argv[0]} failed")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


@dataclass(frozen=True)
class AudioPiece:
    wav: bytes
    start: float
    end: float


def audio_windows(
    path: Path, window=30.0, hop=25.0, minimum=2.0, rms_gate=0.003, *, start=0.0
) -> Iterator[AudioPiece]:
    if "audio" not in media_info(path)["streams"]:
        return
    rate = 16000
    size, step = int(window * rate) * 2, int(hop * rate) * 2
    buffer = bytearray()
    offset = int(start * rate) * 2
    initial = offset

    def emit():
        samples = np.frombuffer(buffer, dtype="<i2").astype(np.float32) / 32768
        if np.sqrt(np.mean(samples * samples)) <= rms_gate:
            return None
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(buffer)
        return AudioPiece(output.getvalue(), offset / (rate * 2),
                          (offset + len(buffer)) / (rate * 2))

    stream = _stream([
        "ffmpeg", "-v", "error", "-ss", str(start), "-i", str(path),
        "-vn", "-ac", "1", "-ar", str(rate),
        "-f", "s16le", "-",
    ], 65536)
    try:
        for block in stream:
            position = 0
            while position < len(block):
                count = min(size - len(buffer), len(block) - position)
                buffer.extend(block[position:position + count])
                position += count
                if len(buffer) == size:
                    piece = emit()
                    if piece is not None:
                        yield piece
                    del buffer[:step]
                    offset += step
        covered = size - step if offset > initial or start else 0
        if len(buffer) - covered >= int(minimum * rate) * 2:
            piece = emit()
            if piece is not None:
                yield piece
    finally:
        stream.close()


def sampling_interval(duration: float, every=3.0, max_frames=1200) -> float:
    return max(every, duration / max_frames)


def average_hash(sample: bytes) -> int:
    mean = sum(sample) // len(sample)
    return sum(1 << index for index, pixel in enumerate(sample) if pixel > mean)


@dataclass(frozen=True)
class FramePiece:
    image: ImagePart
    start: float
    end: float
    thumbnail: bytes | None = None


def keyframes(
    path: Path, every=3.0, max_frames=1200, max_dist=4, *, start=0.0
) -> Iterator[FramePiece]:
    info = media_info(path)
    duration = info["duration"]
    if "video" not in info["streams"] or not duration:
        return
    step = sampling_interval(duration, every, max_frames)
    initial = min(0.5, duration / 2)
    first = max(initial, start)
    offset = round((first - initial) / step)
    previous = None
    last_hash = None
    stream = _stream([
        "ffmpeg", "-v", "error", "-ss", str(first), "-i", str(path), "-vf",
        f"fps=1/{step}:start_time=0:round=up,scale=8:8:flags=area,format=gray",
        "-frames:v", str(max_frames - offset),
        "-f", "rawvideo", "-",
    ], 64)
    try:
        for index, sample in enumerate(stream):
            if len(sample) != 64:
                raise ExtractionError("incomplete frame sample")
            second = first + index * step
            if second >= duration:
                break
            hashed = average_hash(sample)
            if last_hash is not None and (hashed ^ last_hash).bit_count() <= max_dist:
                continue
            last_hash = hashed
            if previous is not None:
                # Look ahead with gray bytes only; closing a pass must not decode another PNG.
                yield FramePiece(previous.image, previous.start, second, previous.thumbnail)
            data = _media_command([
                "ffmpeg", "-v", "error", "-ss", str(second), "-i", str(path),
                "-frames:v", "1", "-vf",
                "scale=1024:1024:force_original_aspect_ratio=decrease", "-f", "image2pipe",
                "-vcodec", "png", "-",
            ])
            previous = FramePiece(_image("-", 70, data=data), second, duration,
                                  _thumbnail("-", data=data)
                                  if previous is None and not start else None)
        if previous is not None:
            yield previous
    finally:
        stream.close()


def extract_audio(path: Path, *, audio=True, start=0.0) -> Extracted:
    if not audio:
        return Extracted([], state="skipped", detail="audio search is off")
    duration = media_info(path)["duration"]
    windows = audio_windows(path, start=start)
    try:
        segments = [Segment("audio", "audio", loc=p.start, loc_end=p.end, audio=p.wav)
                    for p in islice(windows, 16)]
    finally:
        windows.close()
    info = {"duration": duration}
    state = "done" if segments or start else "skipped"
    if len(segments) == 16 and duration - segments[-1].loc_end >= 2:
        info["audio_next"] = segments[-1].loc + 25
        state = "partial"
    return Extracted(segments, info, state,
                     detail="silent audio" if state == "skipped" else None)


def extract_video(path: Path, *, audio=True, start=0.0, frame_start=0.0) -> Extracted:
    info = media_info(path)
    segments = []
    thumbnail = None
    if frame_start is not None and not start:
        frames = keyframes(path, start=frame_start)
        try:
            for piece in islice(frames, 16):
                thumbnail = thumbnail or piece.thumbnail
                segments.append(Segment("frame", "image", loc=piece.start, loc_end=piece.end,
                                        image=piece.image))
        finally:
            frames.close()
    result = Extracted(segments, {"duration": info["duration"]}, thumbnail=thumbnail)
    if segments:
        if segments[-1].loc_end < info["duration"]:
            result.info["frame_next"] = segments[-1].loc_end
            result.state = "partial"
        elif audio and "audio" in info["streams"]:
            result.info["audio_next"] = 0
            result.state = "partial"
        return result
    if audio and "audio" in info["streams"]:
        try:
            soundtrack = extract_audio(path, start=start)
            result.segments.extend(soundtrack.segments)
            result.info.update(soundtrack.info)
            if soundtrack.state == "partial":
                result.state = "partial"
        except ExtractionError as error:
            if frame_start is not None and not start:
                raise
            result.state, result.detail = "partial", str(error)
    return result


EXTRACTORS = {"text": extract_text, "pdf": extract_pdf, "image": extract_image,
              "video": extract_video, "audio": extract_audio}


def extract(
    path: Path, kind: str, start: int = 1, audio=True, image_budget=140, frame_start=0.0
) -> Extracted:
    options = {"pdf": {"start": start}, "image": {"image_budget": image_budget},
               "video": {"audio": audio, "start": start - 1, "frame_start": frame_start},
               "audio": {"audio": audio, "start": start - 1}}
    return EXTRACTORS[kind](path, **options.get(kind, {}))
