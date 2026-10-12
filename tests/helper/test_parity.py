import base64
import json
import math
import subprocess
from pathlib import Path

import numpy as np
import pytest
from omafindd.embedder import Embedder, ImageUrl, InputAudio, Text

REF = Path(__file__).resolve().parents[1] / "fixtures" / "reference"
THRESHOLD = 0.999
PATCH_AREA = 48 * 48

pytestmark = pytest.mark.manual

IMAGES = {
    "screen-280": "screen.png",
    "photo-140": "photo.jpg",
    "frame-70": "photo.jpg",
    "photo-280": "photo.jpg",
    "pdfpage-280": "pdfpage.png",
}


def cosine(a, b) -> float:
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def resized(name: str, budget: int) -> ImageUrl:
    """Pre-resize to the size llama.cpp picks for the budget (multiples of 48, budget * 2304 px)."""
    path = REF / name
    width, height = map(int, subprocess.run(
        ["magick", "identify", "-format", "%w %h", f"{path}[0]"],
        capture_output=True, text=True, check=True).stdout.split())
    max_pixels = budget * PATCH_AREA
    w, h = max(48, round(width / 48) * 48), max(48, round(height / 48) * 48)
    if w * h > max_pixels:
        beta = math.sqrt(height * width / max_pixels)
        w, h = (max(48, math.floor(width / beta / 48) * 48),
                max(48, math.floor(height / beta / 48) * 48))
    png = subprocess.run(
        ["magick", f"{path}[0]", "-auto-orient", "-filter", "Catrom", "-resize", f"{w}x{h}!",
         "-alpha", "off", "png:-"], capture_output=True, check=True).stdout
    return ImageUrl("data:image/png;base64," + base64.b64encode(png).decode())


@pytest.fixture(scope="module")
def reference() -> dict:
    return json.loads((REF / "bf16-reference.json").read_text())


async def test_full_mode_matches_bf16_reference(reference):
    meta, vectors = reference["meta"], reference["vectors"]
    recorded = json.loads((REF / "vectors.json").read_text())["vectors"]
    audio_required = "speech" in recorded
    audio_failure = "Speech parity failed. Force `audio` off and update ADR-4."
    inputs = {name: resized(file, meta["image_budget"][name]) for name, file in IMAGES.items()}
    inputs.update({name: Text(meta["prompts"][name])
                   for name in ("query", "document", "query-dog", "document-hello")})
    audio = InputAudio(base64.b64encode((REF / "speech.wav").read_bytes()).decode())
    embedder = Embedder(startup_timeout=180.0)
    await embedder.start("full")
    try:
        names = list(inputs)
        results = dict(zip(names, await embedder.embed([inputs[n] for n in names]), strict=True))
        if audio_required:
            try:
                results["speech"] = (await embedder.embed([audio]))[0]
            except Exception as error:
                pytest.fail(f"{audio_failure} {error}")
    finally:
        await embedder.stop()
    scores = {name: cosine(vector, vectors[name]) for name, vector in results.items()}
    for name, score in scores.items():
        print(f"{name}: {score:.6f}")
    assert {"photo-140", "screen-280", "pdfpage-280"} <= scores.keys()
    if audio_required:
        assert "speech" in scores, audio_failure
        assert scores["speech"] >= THRESHOLD, audio_failure
    assert [name for name, score in scores.items() if score < THRESHOLD] == []
