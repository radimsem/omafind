import hashlib
import json
import math
import os
import re
import selectors
import subprocess
import tempfile
import time
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import opener, paths
from .extractors import ExtractionError, extract_text


def _run(argv):
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    if result.returncode:
        raise ExtractionError(f"{argv[0]} failed")
    return result.stdout


def _lines(item, query):
    path = Path(item["path"])
    temporary = None
    try:
        if item.get("info", {}).get("extracted"):
            text = ""
            for segment in extract_text(path).segments:
                # Extractor chunks overlap by up to 200 characters, including within a line.
                longest = min(200, len(text), len(segment.text))
                overlap = next((size for size in range(longest, 0, -1)
                                if text.endswith(segment.text[:size])), 0)
                if not text:
                    text = "\n" * (int(segment.loc) - 1)
                text += segment.text[overlap:]
            with tempfile.NamedTemporaryFile(dir=paths.preview_dir(), suffix=".txt",
                                             mode="w", delete=False) as stream:
                stream.write(text)
                temporary = path = Path(stream.name)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        words = re.findall(r"[^\W_]+", re.sub(r"^(?:img|pdf|doc|vid|aud|code):", "", query))
        hits = set()
        if words:
            argv = ["rg", "-n", "--json", "-F", "-i"]
            for word in words:
                argv.extend(["-e", word])
            result = subprocess.run([*argv, "--", str(path)], capture_output=True,
                                    text=True, timeout=10)
            if result.returncode not in (0, 1):
                raise ExtractionError("rg failed")
            hits = {value["data"]["line_number"] for line in result.stdout.splitlines()
                    if (value := json.loads(line))["type"] == "match"}
        loc = max(1, int(item.get("loc") or 1))
        end = max(loc, int(item.get("loc_end") or loc + 8))
        jump = (item.get("open_line") or loc) if item["kind"] == "code" else next(
            (no for no in sorted(hits) if loc <= no <= end), loc
        )
        jump = max(1, min(int(jump), len(lines) or 1))
        start, end = max(1, jump - 8), min(len(lines), jump + 8)
        return {"jump": jump, "range": [start, end],
                "lines": [{"no": no, "text": lines[no - 1], "hit": no in hits}
                          for no in range(start, end + 1)]}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _bars(path):
    return list(_cached_bars(str(path), path.stat().st_mtime_ns))


@lru_cache(maxsize=32)
def _cached_bars(path, mtime_ns):
    duration = float(_run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                           "-of", "default=noprint_wrappers=1:nokey=1", str(path)]))
    samples = max(1, round(duration * 400))
    sums, counts = [0] * 64, [0] * 64
    position = 0
    # Stream PCM in bounded blocks; stderr goes to a file to avoid a pipe deadlock.
    with tempfile.TemporaryFile() as errors, subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "400",
         "-f", "s16le", "-"], stdout=subprocess.PIPE, stderr=errors,
    ) as process, selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + 60
        remainder = b""
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise ExtractionError("ffmpeg timeout")
                block = os.read(process.stdout.fileno(), 65536)
                if not block:
                    break
                block = remainder + block
                remainder = block[len(block) // 2 * 2:]
                values = np.frombuffer(block[:len(block) // 2 * 2], dtype="<i2").astype(np.int64)
                offset = 0
                while offset < len(values):
                    bar = min(63, position * 64 // samples)
                    end = len(values) if bar == 63 else min(
                        len(values), offset + ((bar + 1) * samples + 63) // 64 - position)
                    chunk = values[offset:end]
                    sums[bar] += int(chunk @ chunk)
                    counts[bar] += len(chunk)
                    position += len(chunk)
                    offset = end
            if process.wait(timeout=max(.001, deadline - time.monotonic())):
                raise ExtractionError("ffmpeg failed")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    return tuple(min(100, round(100 * math.sqrt(total / count) / 32768)) if count else 0
                 for total, count in zip(sums, counts, strict=True))


def render(item, query="") -> dict:
    kind = item["kind"]
    reply = {"t": "preview", "id": item["id"], "mode": None, "lines": [],
             "jump": item.get("loc"), "range": None, "image": None, "bars": []}
    target = dict(item)
    if item.get("offline"):
        reply.update(mode="image", image=item.get("thumb"))
    elif kind in ("text", "code"):
        reply.update(_lines(item, query), mode="lines")
        target["loc"] = reply["jump"]
        if kind == "code":
            target["open_line"] = reply["jump"]
    elif kind == "image":
        reply.update(mode="image", image=item.get("thumb") or item["path"])
    elif kind == "audio":
        reply.update(mode="bars", bars=_bars(Path(item["path"])))
    elif kind in ("pdf", "video"):
        path = Path(item["path"])
        jump = max(1, int(item.get("loc") or 1)) if kind == "pdf" else item.get("loc") or 0
        key = hashlib.sha256(f"{path}:{path.stat().st_mtime_ns}:{jump}".encode()).hexdigest()
        prefix = paths.preview_dir() / key
        image = prefix.with_suffix(".png" if kind == "pdf" else ".jpg")
        if not image.exists():
            with tempfile.TemporaryDirectory(dir=prefix.parent) as directory:
                temporary = Path(directory) / image.name
                if kind == "pdf":
                    _run(["pdftoppm", "-f", str(jump), "-l", str(jump), "-scale-to", "1024",
                          "-singlefile", "-png", str(path), str(temporary.with_suffix(""))])
                else:
                    _run(["ffmpeg", "-v", "error", "-ss", str(jump), "-i", str(path),
                          "-frames:v", "1", "-vf", "scale=1024:-2", "-y", str(temporary)])
                os.replace(temporary, image)
        reply.update(mode="image", jump=jump, image=str(image))
    reply["opener"] = opener.description(target)["opener"]
    if kind in ("text", "code"):
        reply["editor"] = opener.editor_name(env=os.environ)
    return reply
