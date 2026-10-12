# ADR-4: Stock llama-server subprocess instead of a custom libllama shim

Status: accepted, 2026-10-12 (Phase 0). The Phase 0 query set has not run; see "Phase 0 query set".

## Context

omafind embeds text, images, video frames and audio with one model, `embeddinggemma-2` (Q8_0 plus mmproj). DigUp, the macOS predecessor, links libllama through a custom shim. A Linux port of that shim means maintaining C glue against llama.cpp internals. The alternative is the stock `llama-server` from a pinned tag, driven over loopback `POST /v1/embeddings` with typed content parts.

The decision depended on three open points (spec 5.3): audio through the server, image parity against a bf16 reference, and the cost per item.

## Decision

Run the stock `llama-server` from llama.cpp b11461 (`4d756bc`) as a subprocess, built by `scripts/build-runtime.sh` (Vulkan, static, server and mtmd only). No custom shim.

One local patch: `scripts/llama.cpp-no-logits.patch` (from DigUp). A non-causal embedding context still reserves and clears `n_vocab` floats of logits per token, which is 1 MiB per token with Gemma's 262k vocabulary. The patch skips logits when `embeddings && !causal_attn`. The unpatched build was not measured here; the patch is kept for the reason in its own comment. It touches one line of `src/llama-context.cpp`.

Server flags (`omafindd.embedder.server_argv`): `--embeddings --pooling mean --ctx-size 2048 --batch-size 2048 --ubatch-size 2048 --parallel 16 --kv-unified`, plus `--image-min-tokens 1` in full mode, `--no-mmproj-offload` on CPU and `-ngl 99` or `-ngl 0`. Text mode uses 512 for the three size flags and no mmproj.

Image budgets are not a request field. The client pre-resizes each image with ImageMagick (`magick -filter Catrom -resize WxH!`) to the size llama.cpp itself picks for the budget: dimensions rounded down to multiples of 48, at most `budget * 2304` pixels. The server then sees an image it does not rescale. `--image-min-tokens 1` is needed because the default minimum of 70 tokens upscales a 63-token frame again.

## Probe table

Host: RTX 3060 12 GB, Vulkan0, 6 CPU threads. Reference: sentence-transformers 6.1.0, transformers 5.19.0, torch 2.14.1 bf16 on CUDA, `google/embeddinggemma-2` revision `914f7f89142e33e77833254d9c9b90c3cef7303b`. Model files at revision `bfcd298762cc34d0357ece5ebdd31791a3a374d8`. Command: `scripts/probe.py` under `systemd-run --user --scope -p MemoryMax=8G -p MemorySwapMax=0`.

### Parity (cosine against bf16, required at least 0.999)

| Input | Budget | Cosine |
|---|---|---|
| photo | 140 | 0.999473 |
| photo | 280 | 0.999671 |
| video frame (photo) | 70 | 0.999142 |
| screenshot | 280 | 0.999793 |
| PDF page | 280 | 0.999347 |
| speech clip (audio) | | 0.999748 |
| query text | | 0.999899 |
| document text | | 0.999824 |
| `query-dog` | | 0.999943 |
| `document-hello` | | 0.999917 |

All ten pass. The lowest margin is the 70-token frame. The vectors are stored in `tests/fixtures/reference/vectors.json`, and `tests/helper/test_parity.py` (marked `manual`) re-checks them against `bf16-reference.json`.

ImageMagick resize filters tried (cosine against bf16; the pre-resize uses Catrom, the closest match to PIL bicubic):

| Filter | frame 70 | photo 140 | screen 280 |
|---|---|---|---|
| Catrom (used) | 0.99914 | 0.99947 | 0.99979 |
| Hermite | 0.99874 | 0.99948 | 0.99959 |
| Mitchell | 0.99881 | 0.99918 | 0.99622 |
| Lanczos | 0.99848 | 0.99928 | 0.99733 |
| Triangle | 0.99791 | 0.99894 | 0.99720 |
| Cubic | 0.99513 | 0.99414 | 0.95615 |

### Audio

Works. The speech clip (4 s) goes through `input_audio` with format `wav`: 104 prompt tokens, cosine 0.999741 against the bf16 audio vector. 30 s of audio is 754 prompt tokens. llama.cpp logs "audio input is in experimental stage". `audio` stays available.

### Token budget (llama.cpp issue #30195)

| Setup | 4000 px photo, prompt tokens |
|---|---|
| No flag | 976 (cap 1024 from `n_ubatch`, model default 1120) |
| `--image-max-tokens 70` | 67 |
| `--image-max-tokens 140` | 134 |
| `--image-max-tokens 280` | 270 |
| Client pre-resize to budget 70, 140, 280 (no budget flag) | 67, 134, 270 |

The overhead is 4 tokens over the image tokens (63, 130 and 266 for 432x336, 624x480 and 912x672). The flag is honored at this tag, both for the 4000 px photo and for a 1024x768 one. The budget is a server-wide flag, so one server cannot serve two budgets by flag alone.

The server's own downscale is worse than the client resize, so the pre-resize is the fix, not a guard:

| Budget | Server downscale (flag) | Client pre-resize (Catrom) |
|---|---|---|
| 70 | 0.99213 | 0.99914 |
| 140 | 0.99281 | 0.99947 |
| 280 | 0.98596 | 0.99967 |

Without `--image-min-tokens 1`, the 70-token frame scores 0.99047.

### Rates (seconds per item, warm server)

Single request median (5 runs on GPU, 3 on CPU), then per item inside one batch (8 on GPU, 4 on CPU). Time to resize with `magick` is not included.

| Kind | Prompt tokens | GPU single | GPU batched | `-ngl 0` single | `-ngl 0` batched |
|---|---|---|---|---|---|
| Text chunk, 1800 characters | 433 | 0.031 | 0.021 | 0.091 | 0.042 |
| Image, budget 140 | 134 | 0.097 | 0.091 | 1.44 | 1.31 |
| Video frame, budget 70 | 67 | 0.052 | 0.044 | 0.68 | 0.65 |
| Audio, 30 s | 754 | 0.144 | 0.143 | 1.42 | 1.52 |

At these rates 10,000 images at budget 140 take about 15 minutes on the GPU and about 3.6 hours with `-ngl 0`.

### Startup, VRAM and RSS

Startup is seconds from spawn to `/health` 200. The first start after boot or a cache flush took 6.9 s in full mode (server log); repeat starts are below.

| Mode, device | Startup | VRAM after start | VRAM after embed | RSS after start | RSS after embed (peak) |
|---|---|---|---|---|---|
| text, GPU | 1.4 s | 233 MiB | 233 MiB | 362 MiB | 362 MiB (504) |
| full, GPU | 1.7 to 2.6 s | 1218 MiB | 1258 MiB | 467 MiB | 493 to 539 MiB (508 to 539) |
| text, `-ngl 0` | 1.3 s | 68 MiB | 68 MiB | 502 to 530 MiB | 503 to 530 MiB |
| full, `-ngl 0` | 1.5 to 1.7 s | 239 MiB | 274 MiB | 1079 MiB | 1161 to 1200 MiB |

`-ngl 0` still creates a Vulkan device, hence the small VRAM figures. Full mode on GPU stays under the 1.5 GB gate of spec 2.4.

### Phase 0 query set

Not run. The set needs 20 photos from the user's own files. `~/Pictures` holds 389 files and all are screenshots; `~/Obrazky` and `~/Photos` do not exist. `evals/phase0.json` has `"approved": false` and no pairs. First-hit count: unmeasured. `scripts/probe.py --stage eval` computes it once pairs exist (photos at budget 140, queries with the query prompt, rank by cosine). The phase 0 gate in spec 9.3 stays open until then.

## Consequences

- No C glue to maintain. The runtime upgrades by changing the tag in `scripts/build-runtime.sh`, then re-running `scripts/probe.py` and `tests/helper/test_parity.py`.
- Every image path in the indexer must pre-resize (spec 5.2). Sending raw images costs up to 0.014 cosine and, without a flag, up to 1024 tokens per image.
- Audio input is marked experimental upstream. A tag bump can regress it; the parity test covers the speech clip.
- The no-logits patch must be re-applied on each tag bump. If it stops applying, the build fails loudly.

## Revisit

Reconsider the libllama shim, for media only, when any of these holds:

- `input_audio` fails or drops below cosine 0.999 on a new tag and no flag or pre-processing fixes it. `audio` is then forced off first.
- Image parity drops below 0.999 for photo, screenshot or PDF page and a client-side fix does not restore it. This is the kill criterion for the roadmap: image parity with no fix in sight stops the project at Phase 0.
- The no-logits patch cannot be carried on a needed tag.
