#!/usr/bin/env python3
"""Phase 0 probes for the stock llama-server runtime (ADR-4, spec 5.3).

Run inside a memory cap, one heavy job at a time:

    systemd-run --user --scope --quiet --collect -p MemoryMax=8G -p MemorySwapMax=0 -- \
        uv run --project helper python scripts/probe.py [--stage facts,parity,audio,...]

Stages:
  facts   startup seconds, VRAM and RSS per mode on GPU and with -ngl 0
  parity  cosine against tests/fixtures/reference/bf16-reference.json, writes vectors.json
  audio   one speech clip through input_audio
  budget  a 4000 px photo at budgets 70, 140 and 280 (llama.cpp issue #30195)
  rates   seconds per item for text, image (140), video frame (70) and 30 s audio
  eval    first-hit count of evals/phase0.json (text query to photo, budget 140)

Images are pre-resized with ImageMagick (`magick`) to the pixel area of their token budget,
with the dimensions llama.cpp itself would pick (multiples of 48, at most budget * 2304 px).
"""

import argparse
import asyncio
import base64
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
from omafindd.embedder import (
    Embedder,
    EmbeddingError,
    ImageUrl,
    InputAudio,
    Text,
    build_request,
)

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "tests" / "fixtures" / "reference"
PATCH_AREA = 48 * 48
MODEL_REVISION = "bfcd298762cc34d0357ece5ebdd31791a3a374d8"
THRESHOLD = 0.999
FILTER = "Catrom"
SERVER_FLAGS: tuple[str, ...] = ()


def runtime_tag() -> dict:
    binary = Path.home() / ".local/share/omafind/runtime/bin/llama-server"
    version = subprocess.run([str(binary), "--version"], capture_output=True, text=True)
    output = (version.stdout + version.stderr).strip()
    return {"tag": "b11461", "commit": "4d756bc", "version_output": output}


def target_size(width: int, height: int, budget: int) -> tuple[int, int]:
    """The size the gemma4 preprocessor picks (mtmd-image.cpp calc_size_preserved_ratio)."""
    align, max_pixels = 48, budget * PATCH_AREA
    w = max(align, round(width / align) * align)
    h = max(align, round(height / align) * align)
    if w * h > max_pixels:
        beta = math.sqrt(height * width / max_pixels)
        h = max(align, math.floor(height / beta / align) * align)
        w = max(align, math.floor(width / beta / align) * align)
    return w, h


def image_size(path: Path) -> tuple[int, int]:
    out = subprocess.run(["magick", "identify", "-format", "%w %h", f"{path}[0]"],
                         capture_output=True, text=True, check=True).stdout.split()
    return int(out[0]), int(out[1])


def data_url(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def raw_image(path: Path) -> ImageUrl:
    mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    return ImageUrl(data_url(path.read_bytes(), mime))


def resized_image(path: Path, budget: int, flt: str = FILTER) -> tuple[ImageUrl, tuple[int, int]]:
    width, height = target_size(*image_size(path), budget)
    out = subprocess.run(
        ["magick", f"{path}[0]", "-auto-orient", "-filter", flt, "-resize", f"{width}x{height}!",
         "-alpha", "off", "png:-"], capture_output=True, check=True).stdout
    return ImageUrl(data_url(out, "image/png")), (width, height)


def audio_part(path: Path) -> InputAudio:
    return InputAudio(base64.b64encode(path.read_bytes()).decode())


def audio_30s(directory: Path) -> Path:
    with wave.open(str(REF / "speech.wav")) as src:
        params, frames = src.getparams(), src.readframes(src.getnframes())
    wanted = params.framerate * 30 * params.sampwidth * params.nchannels
    data = (frames * (wanted // len(frames) + 1))[:wanted]
    out = directory / "speech-30s.wav"
    with wave.open(str(out), "wb") as dst:
        dst.setparams(params)
        dst.writeframes(data)
    return out


def cosine(a, b) -> float:
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


class Run:
    """One llama-server through Embedder, with an optional forced CPU and extra server flags."""

    def __init__(self, mode: str, device: str, extra: tuple[str, ...] = ()):
        self.mode, self.device, self.extra = mode, device, (*SERVER_FLAGS, *extra)
        self.log = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False)
        self.startup = 0.0
        self.embedder = Embedder(runner=self._runner, spawner=self._spawn, startup_timeout=180.0)

    def _runner(self, *args, **kwargs):
        if self.device == "cpu":
            return subprocess.CompletedProcess(args, 0, stdout="0\n", stderr="")
        return subprocess.run(*args, **kwargs)

    async def _spawn(self, *argv, **kwargs):
        kwargs.update(stdout=self.log, stderr=self.log)
        return await asyncio.create_subprocess_exec(*argv, *self.extra, **kwargs)

    async def __aenter__(self):
        started = time.monotonic()
        await self.embedder.start(self.mode)
        self.startup = time.monotonic() - started
        return self

    async def __aexit__(self, *exc):
        await self.embedder.stop()
        self.log.close()
        os.unlink(self.log.name)

    @property
    def pid(self) -> int:
        return self.embedder._process.pid

    def memory(self) -> dict:
        status = Path(f"/proc/{self.pid}/status").read_text()
        kib = {line.split(":")[0]: int(line.split()[1]) for line in status.splitlines()
               if line.startswith(("VmRSS", "VmHWM"))}
        vram = None
        out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True)
        for line in out.stdout.splitlines():
            pid, used = (field.strip() for field in line.split(","))
            if int(pid) == self.pid:
                vram = int(used)
        return {"rss_mib": round(kib["VmRSS"] / 1024), "rss_peak_mib": round(kib["VmHWM"] / 1024),
                "vram_mib": vram}

    def argv(self) -> list[str]:
        return Path(f"/proc/{self.pid}/cmdline").read_bytes().decode().split("\0")[:-1]

    def log_text(self) -> str:
        self.log.flush()
        return Path(self.log.name).read_text()

    async def embed(self, parts):
        return await self.embedder.embed(parts)

    async def usage(self, parts) -> int:
        response = await self.embedder._client.post("/v1/embeddings", json=build_request(parts))
        response.raise_for_status()
        return response.json()["usage"]["prompt_tokens"]


def reference() -> dict:
    return json.loads((REF / "bf16-reference.json").read_text())


def parity_inputs(meta: dict, flt: str) -> dict:
    prompts, budgets = meta["prompts"], meta["image_budget"]
    sources = {"screen-280": "screen.png", "photo-140": "photo.jpg", "frame-70": "photo.jpg",
               "photo-280": "photo.jpg", "pdfpage-280": "pdfpage.png"}
    inputs = {name: resized_image(REF / file, budgets[name], flt)[0]
              for name, file in sources.items()}
    inputs["speech"] = audio_part(REF / "speech.wav")
    inputs.update({name: Text(prompts[name]) for name in
                   ("query", "document", "query-dog", "document-hello")})
    return inputs


async def stage_facts(results: dict) -> None:
    facts = {}
    for device in ("gpu", "cpu"):
        for mode in ("text", "full"):
            async with Run(mode, device) as run:
                row = {"startup_s": round(run.startup, 2), "after_start": run.memory(),
                       "argv": run.argv()[1:]}
                parts = [Text("task: search result | query: warm up")]
                if mode == "full":
                    parts.append(resized_image(REF / "photo.jpg", 140)[0])
                await run.embed(parts)
                row["after_embed"] = run.memory()
                facts[f"{mode}-{device}"] = row
    results["facts"] = facts


async def stage_parity(results: dict, flt: str) -> None:
    ref = reference()
    inputs = parity_inputs(ref["meta"], flt)
    async with Run("full", "gpu") as run:
        names = list(inputs)
        try:
            vectors = await run.embed([inputs[name] for name in names])
            audio_error = None
        except EmbeddingError as error:
            audio_error = str(error)
            names = [name for name in names if name != "speech"]
            vectors = await run.embed([inputs[name] for name in names])
    rows, stored = {}, {}
    for name, vector in zip(names, vectors, strict=True):
        value = cosine(vector, ref["vectors"][name])
        rows[name] = {"cosine": round(value, 6), "pass": value >= THRESHOLD}
        stored[name] = [round(float(x), 6) for x in vector.astype(np.float32)]
    meta = dict(ref["meta"])
    meta.update({"runtime": runtime_tag(), "model_revision": MODEL_REVISION, "resize_filter": flt,
                 "resize": "magick; dimensions as llama.cpp calc_size_preserved_ratio, "
                           "budget * 2304 px",
                 "reference_cosine": {name: row["cosine"] for name, row in rows.items()}})
    meta.pop("digup_cosine", None)
    (REF / "vectors.json").write_text(json.dumps({
        "made_with": "llama-server b11461 (Vulkan, no-logits patch), embeddinggemma-2-Q8_0 + "
                     "mmproj, generated by scripts/probe.py",
        "vectors": stored, "meta": meta}, indent=1) + "\n")
    results["parity"] = {"filter": flt, "rows": rows, "audio_error": audio_error,
                         "all_pass": all(row["pass"] for row in rows.values())}


async def stage_audio(results: dict) -> None:
    async with Run("full", "gpu") as run:
        try:
            vector = (await run.embed([audio_part(REF / "speech.wav")]))[0]
            value = cosine(vector, reference()["vectors"]["speech"])
            tokens = await run.usage([audio_part(REF / "speech.wav")])
            results["audio"] = {"works": True, "cosine": round(value, 6), "prompt_tokens": tokens}
        except EmbeddingError as error:
            results["audio"] = {"works": False, "error": str(error),
                                "log_tail": run.log_text()[-800:]}


async def stage_budget(results: dict, flt: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        big = Path(tmp) / "photo-4000.jpg"
        subprocess.run(["magick", str(REF / "photo.jpg"), "-filter", "Lanczos", "-resize",
                        "4000x4000", "-quality", "92", str(big)], check=True)
        size = image_size(big)
        ref = reference()["vectors"]
        rows = {"source": {"file": "photo.jpg upscaled", "px": size}}
        async with Run("full", "gpu") as run:
            rows["default_server"] = {"argv_has_budget_flag": False,
                                      "raw_4000px_tokens": await run.usage([raw_image(big)])}
            for budget in (70, 140, 280):
                part, dims = resized_image(big, budget, flt)
                tokens = await run.usage([part])
                vector = (await run.embed([part]))[0]
                rows["default_server"][f"preresized_{budget}"] = {
                    "px": dims, "soft_tokens": dims[0] * dims[1] // PATCH_AREA,
                    "prompt_tokens": tokens,
                    "cosine_to_photo_ref": round(cosine(vector, ref[f"photo-{budget}"]), 6)
                    if f"photo-{budget}" in ref else None}
            rows["default_server"]["flag_in_log"] = [
                line for line in run.log_text().splitlines() if "image_max_tokens" in line]
        for budget in (70, 140, 280):
            async with Run("full", "gpu", ("--image-max-tokens", str(budget))) as run:
                tokens = await run.usage([raw_image(big)])
                small = await run.usage([raw_image(REF / "photo.jpg")])
                vector = (await run.embed([raw_image(REF / "photo.jpg")]))[0]
                ref_name = {70: "frame-70", 140: "photo-140", 280: "photo-280"}[budget]
                rows[f"flag_{budget}"] = {
                    "raw_4000px_tokens": tokens, "raw_1024x768_tokens": small,
                    "server_resize_cosine_to_ref": round(cosine(vector, ref[ref_name]), 6),
                    "log": [line for line in run.log_text().splitlines()
                            if "image_max_tokens" in line or "image_max_pixels" in line]}
        results["budget"] = rows


async def stage_rates(results: dict, flt: str) -> None:
    chunk = ("title: notes | text: " + "Flight to Tokyo Haneda on November 3. Then the train to "
             "Kamakura to see the Great Buddha, and back for dinner in Shibuya. " * 20)[:1800]
    with tempfile.TemporaryDirectory() as tmp:
        clip = audio_30s(Path(tmp))
        photo = resized_image(REF / "photo.jpg", 140, flt)[0]
        frame = resized_image(REF / "photo.jpg", 70, flt)[0]
        kinds = {"text_1800_chars": lambda i: Text(f"{i} {chunk}"),
                 "image_140": lambda i: photo, "frame_70": lambda i: frame,
                 "audio_30s": lambda i: audio_part(clip)}
        rows = {}
        for device, singles, batch in (("gpu", 5, 8), ("cpu", 3, 4)):
            async with Run("full", device) as run:
                for kind, make in kinds.items():
                    await run.embed([make(0)])
                    times = []
                    for i in range(singles):
                        started = time.monotonic()
                        await run.embed([make(i + 1)])
                        times.append(time.monotonic() - started)
                    parts = [make(i + 100) for i in range(batch)]
                    started = time.monotonic()
                    await run.embed(parts)
                    per_item = (time.monotonic() - started) / batch
                    rows.setdefault(kind, {})[device] = {
                        "single_median_s": round(statistics.median(times), 3),
                        "batch": batch, "batched_per_item_s": round(per_item, 3),
                        "prompt_tokens": await run.usage([make(0)])}
        results["rates"] = rows


async def stage_eval(results: dict, flt: str) -> None:
    spec = json.loads((ROOT / "evals" / "phase0.json").read_text())
    pairs = spec["pairs"]
    if not pairs:
        results["eval"] = {"pairs": 0, "note": "no pairs in evals/phase0.json"}
        return
    root = Path(spec["root"]).expanduser()
    files = sorted({pair["file"] for pair in pairs})
    async with Run("full", "gpu") as run:
        images = []
        for file in files:
            images.append(resized_image(root / file, 140, flt)[0])
        photos = np.stack([v.astype(np.float32) for v in await _embed_all(run, images)])
        queries = [Text(f"task: search result | query: {pair['query']}") for pair in pairs]
        query_vectors = np.stack([v.astype(np.float32) for v in await _embed_all(run, queries)])
    scores = query_vectors @ photos.T
    ranks = []
    for row, pair in zip(scores, pairs, strict=True):
        order = list(np.argsort(-row))
        ranks.append(order.index(files.index(pair["file"])) + 1)
    results["eval"] = {"pairs": len(pairs), "photos": len(files),
                       "first_hit": sum(rank == 1 for rank in ranks),
                       "top3": sum(rank <= 3 for rank in ranks), "ranks": ranks}


async def _embed_all(run: Run, parts: list) -> list:
    vectors = []
    for offset in range(0, len(parts), 4):
        vectors.extend(await run.embed(parts[offset:offset + 4]))
    return vectors


STAGES = ("facts", "parity", "audio", "budget", "rates", "eval")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--stage", default=",".join(STAGES))
    parser.add_argument("--filter", default=FILTER, help="ImageMagick resize filter")
    parser.add_argument("--server-flags", default="", help="extra llama-server flags for every run")
    parser.add_argument("--results", help="write the results JSON here (merged into a file)")
    args = parser.parse_args()
    global SERVER_FLAGS
    SERVER_FLAGS = tuple(args.server_flags.split())
    results = {"runtime": runtime_tag(), "server_flags": list(SERVER_FLAGS)}
    stages = args.stage.split(",")
    for stage in stages:
        started = time.monotonic()
        print(f"stage {stage}", file=sys.stderr, flush=True)
        function = globals()[f"stage_{stage}"]
        if stage in {"parity", "budget", "rates", "eval"}:
            await function(results, args.filter)
        else:
            await function(results)
        elapsed = time.monotonic() - started
        print(f"stage {stage} done in {elapsed:.1f}s", file=sys.stderr, flush=True)
    if args.results:
        path = Path(args.results)
        merged = json.loads(path.read_text()) if path.exists() else {}
        merged.update(results)
        path.write_text(json.dumps(merged, indent=1))
    print(json.dumps(results, indent=1))
    parity = results.get("parity")
    return 1 if parity and not parity["all_pass"] else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
