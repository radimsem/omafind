# Multimodal content search for Omarchy: what DigUp + EmbeddingGemma 2 prove, and the plan for a plugin

Research date: 2026-10-11. Sources: Reddit thread [`1x2eeds`](https://www.reddit.com/r/LocalLLaMA/comments/1x2eeds/opensource_mac_app_that_runs_embeddinggemma_2/), DigUp source at HEAD `6faa29e`, the [`google/embeddinggemma-2`](https://huggingface.co/google/embeddinggemma-2) card and Google docs, the local `omaone` checkout, and live measurements on this host. Two background research passes wrote the underlying findings; this note is self-contained — every claim carries its primary-source link, and author-reported numbers are marked as such.

## 1. Proposal

**Build a standalone Omarchy 4 plugin — working name `omafind` (`radimsem.omafind`) — that finds any image, video, audio or text file on the host's drive from one natural-language query. Do not put it inside omaone.**

The architecture is not speculative: [DigUp](https://github.com/ARahim3/DigUp) (MIT, native Swift, 658 stars, released v0.6.0 on 2026-10-09) already ships exactly this design on macOS with **one model** — [EmbeddingGemma 2](https://huggingface.co/google/embeddinggemma-2), Apache-2.0, released 2026-10-06 — running as GGUF Q8_0 on llama.cpp. Its model does the work that on Linux would otherwise need a captioner + ASR + OCR + CLIP zoo: all four modalities embed into one shared 768-d space, so a text query matches a photo, a video frame or a 30 s audio window directly. Every Apple-specific piece (FSEvents, Vision OCR, AVFoundation, vDSP, QuickLook) has an obvious Linux or omaone-convention replacement; the search engine itself (SQLite + FTS5 + fp16 vector blobs + z-score/word-coverage fusion) is portable as designed.

| # | Proposal | Recommendation | Why |
|---|---|---|---|
| P1 | Product placement | New plugin `omafind`; clone of omaone's skeleton (thin QML + uv-locked Python helper + JSON-lines socket + systemd user unit) | omaone's ADR 0001 and its Inbox/Fuse surfaces are scoped to agent routing; a whole-drive index is a second product. The skeleton is proven and `omarchy plugin validate`-clean ([omaone manifest](https://github.com/radimsem/omaone), AGENTS.md rules) |
| P2 | Model | EmbeddingGemma 2 (740M, all modalities) via `ggml-org/embeddinggemma-2-GGUF`: `embeddinggemma-2-Q8_0.gguf` (310 MB) + `mmproj-embeddinggemma-2-Q8_0.gguf` (555 MB, image+audio encoders), pinned revision + sha256 like DigUp does | Single-tower shared space kills the captioner/ASR chain; Apache-2.0 and ungated (unlike v1); 865 MB total fits the RTX 3060 with ~1 GB working set. [ggml-org tree](https://huggingface.co/ggml-org/embeddinggemma-2-GGUF/tree/main), [DigUp ModelFiles.swift](https://github.com/ARahim3/DigUp/blob/HEAD/Sources/DigUpKit/ModelFiles.swift) |
| P3 | Runtime | llama.cpp with CUDA; fallback CPU/Vulkan. Build pinned tag with a Linux port of DigUp's `scripts/build-llama.sh` (+ their no-logits patch); check Arch `extra/llama-cpp` only if its build knows `embedding_gemma2`. Ollama (`extra/ollama`, [library entry](https://ollama.com/library/embeddinggemma-2)) as fallback path in the spike | DigUp's shipped path is llama.cpp ("minimal and efficient", tested vs mlx-vlm and LiteRT, comment `pf6v9dd`); it gives on-demand process lifecycle and the smallest RAM. [build-llama.sh](https://github.com/ARahim3/DigUp/blob/HEAD/scripts/build-llama.sh) |
| P4 | Never F16 | Ship only Q8_0/BF16 files; reject F16 GGUFs in the downloader | Google: fp16 activations overflow → NaN or silently degraded vectors ([card "Numerical Precision"](https://huggingface.co/google/embeddinggemma-2)); DigUp header comment: "Never the F16 files" |
| P5 | Storage | One SQLite (WAL): `files` + `segments` (768×fp16 L2-normalized BLOB, `loc` = page/second) + FTS5 keyword table; brute-force fp16 scan in RAM; **no vector database** | DigUp runs this in production: ~20k vectors scan in a few ms; at this host's scale (~300–500k segments) numpy/BLAS brute force stays ≈10–30 ms, well inside query budget. [IndexStore.swift](https://github.com/ARahim3/DigUp/blob/HEAD/Sources/DigUpKit/IndexStore.swift) |
| P6 | Ranking | Port DigUp's fusion: per-modality-centered z-score of cosine + 2·wordCoverage^1.5 + 1 kind hint; candidate gate z≥2 or coverage≥0.5 | Their eval: fusion 0.88 vs 0.73 R@1 for RRF (comment `pf5627s`); raw cosine is compressed (unrelated ≈0.55–0.60 vs good ≈0.67–0.86, `pf5aonw`) |
| P7 | Chunking | Per-modality granularity exactly as DigUp §2 below: 1 vector per image / PDF page / ~1800-char chunk / 30 s audio window (25 s hop) / deduped video keyframe (every 3 s, ≈1/shot); best segment wins and gives the jump pointer | The model's 8K context (max ~29 images, 58 frames, 327 s audio per input) makes chunking the only viable design, and chunking makes the limits irrelevant (OP `pf3zsvw`) |
| P8 | Freshness | Full first crawl with parallel `getdents` walk; then per-directory **inotify** (watchdog) on the indexed roots; restart reconciles by size/mtime re-walk of dirty roots | Unprivileged inotify is enough for a `$HOME`-scoped index; fanotify/root daemon unnecessary. The earlier [fsearch note](2026-10-09-fsearch-macos-linux-portability.md) measured a no-stat crawl of `~` at 0.65 s, so reconciliation is cheap. DigUp's model: "no rescans; compares size/mtime" (`pf4bwaz`) |
| P9 | Name search | Out of scope: keep `plocate` for whole-disk name lookup (already installed here, 1–8 ms) and let the FTS5 name column cover the indexed set | fsearch note §8: name indexing is solved on Linux; this plugin's value is *content* semantics |
| P10 | Process lifecycle | `omafind-embed` helper binary (or `omaoned` subprocess) that loads the model on demand, serves JSON-lines, **exits when idle** → model RAM returns to OS; query path loads only the text part | DigUp: idle 15–30 MB, helper exits after work, query loads ~250 MB text-only encoder (post body; comment `pf5eos4`) |
| P11 | Code search | Opt-in, separate `code.sqlite` index, `git ls-files` walk, queried only behind a `code:` prefix | DigUp's shipped design ([CodeExtractor.swift](https://github.com/ARahim3/DigUp/blob/HEAD/Sources/DigUpKit/CodeExtractor.swift)); keeps agent-repo noise out of the content index |
| P12 | Security | Beat the three Reddit criticisms: secrets/exclude filter runs **globally at crawl time** (DigUp's was code-only — admitted, `pf4hr1n`), index dir mode 0700 + `*.noindex` respect, no telemetry, update check opt-in | Thread criticism `pf2rv4j`, `pf3265v`; `Rules.swift` shows the fix is a wiring job, not new logic |
| P13 | Jump-to-target | `evince --page` / `mpv --start` / `imv` / `xdg-open` driven by `segments.loc` (page, start-second, line) | Host has evince, mpv, imv installed (measured 2026-10-11); DigUp's headline UX is "jumps to the page/moment" |

## 2. What DigUp is, and what it proves

| Item | Value | Source |
|---|---|---|
| What | "Search your Mac by what's in your files" — menubar app, hotkey ⇧⌘Space, QuickLook preview, opens at page/moment | [repo](https://github.com/ARahim3/DigUp), [README](https://raw.githubusercontent.com/ARahim3/DigUp/HEAD/README.md) |
| Stack | Swift ≈16.7k lines + llama.cpp (tag b11461 + no-logits patch, Metal, mtmd); one model for every modality; "no Python" in the shipped app (the `worker/` MLX package is an eval-only reference runtime) | [Package.swift](https://raw.githubusercontent.com/ARahim3/DigUp/HEAD/Package.swift), [LlamaEmbedder.swift](https://raw.githubusercontent.com/ARahim3/DigUp/HEAD/Sources/LlamaRuntime/LlamaEmbedder.swift), [worker/pyproject.toml](https://raw.githubusercontent.com/ARahim3/DigUp/HEAD/worker/pyproject.toml) |
| Reception | Posted 2026-10-10 12:43 UTC by u/A-Rahim; score 353, ratio 0.96, 179 comments; single contributor, 658★, MIT, one release v0.6.0 (2026-10-09) | Reddit API via [Arctic Shift](https://arctic-shift.photon-reddit.com/api/posts/ids?ids=1x2eeds) (reddit.com itself bot-walls anonymous readers), [repo API](https://api.github.com/repos/ARahim3/DigUp) |
| Model pin | `ggml-org/embeddinggemma-2-GGUF` rev `bfcd298…`, both files sha256-verified; parity gate: reference vectors (`cosine ≥ 0.999` vs mlx-vlm bf16) in `ReferenceVectorTests.swift` block llama.cpp upgrades | [ModelFiles.swift](https://github.com/ARahim3/DigUp/blob/HEAD/Sources/DigUpKit/ModelFiles.swift), [ReferenceVectorTests.swift](https://github.com/ARahim3/DigUp/blob/HEAD/Tests/LlamaRuntimeTests/ReferenceVectorTests.swift) |

Extraction matrix (from [Extractors.swift](https://github.com/ARahim3/DigUp/blob/HEAD/Sources/DigUpKit/Extractors.swift), [MediaExtractors.swift](https://github.com/ARahim3/DigUp/blob/HEAD/Sources/DigUpKit/MediaExtractors.swift), [Indexer.swift](https://github.com/ARahim3/DigUp/blob/HEAD/Sources/DigUpKit/Indexer.swift)) — the strategy plan reuses the granularity, replaces the APIs:

| Modality | Mac API used | Segment = vector | Notes |
|---|---|---|---|
| Photos | ImageIO (thumbnail decode) | 1 per image, 140-token budget | |
| Screenshots | Apple Vision OCR + `kMDItemIsScreenCapture` xattr | OCR → FTS5 only (schema 2→3 dropped OCR vectors) | 280-token image budget; OCR ~0.1 s/screenshot (author-reported) |
| PDF | PDFKit, page by page | per page (~6 KB); pages <200 chars rendered as image | >50-page PDFs: first 30 pages in pass 1; hard cap 5k pages |
| Text/docs | Cocoa text system / tag-strip | ~1800-char chunks, 200 overlap | cap 5k chunks |
| Audio | AVFoundation → 16 kHz mono | 30 s window, 25 s hop, RMS-silent skipped | any length, streaming |
| Video | AVFoundation | frame every 3 s, kept on 8×8 avg-hash change (≈1/shot), ≤1200 frames, 70-token budget + audio windows | score = max over frames/audio |
| Code | `git ls-files` | ≤1800-char line stretches, own `code.sqlite` | `code:` prefix only |
| Not read | — | — | Excel, PowerPoint, archives, model weights |

Author-reported performance (his M-series Macs, partly synthetic ~380-file testbed, 111+68 queries — **not independently verified**): 865 MB model download; results ~100–120 ms after typing stops; idle 15–30 MB; indexing peak <2 GB; 100k photos ≈ 160 MB index; new file searchable in 1–2 s; evals ship in [`evals/`](https://github.com/ARahim3/DigUp/tree/HEAD/evals).

Criticisms from the thread worth engineering (comment ids via [Arctic Shift comments](https://arctic-shift.photon-reddit.com/api/comments/search?link_id=1x2eeds&limit=100)): index unencrypted, relies on FileVault (`pf2rv4j`/`pf4hr1n`); secrets filter was code-only, "getting fixed" (`pf4hr1n`); semantic-only misses abstract-doc recall and text-in-screenshot (`important__matter`, `pf2kujr`) — DigUp's answer is exactly the FTS5 keyword leg + fusion, which is why P6 keeps both legs; "isn't this Spotlight?" answered by *content* + jump-to-moment. The author committed to official Linux/Windows support (`pf5bph2`, `pf9oacj`) — a Linux port existing today is UNVERIFIED.

Mac→Linux port map: FSEvents→inotify; Vision OCR→tesseract (installed, Apache-2.0); PDFKit→pdftotext/pypdf + page render; AVFoundation→ffmpeg (installed, n9.0.1); ImageIO→pillow; vDSP→numpy/BLAS; QuickLook/osascript→`xdg-open`/mpv/evince/imv; Sparkle→Omarchy plugin update flow; Metal→CUDA. Portable as-is: the SQLite schema, the ranking math, chunking/windowing constants, prompt framing, the GGUF files, the evals. The UI was always going to be QML, not Swift.

## 3. What EmbeddingGemma 2 is (verified)

Announced 2026-10-06 ([launch blog](https://blog.google/innovation-and-ai/technology/developers-tools/embeddinggemma-2/), [Gemma docs hub](https://ai.google.dev/gemma/docs/embeddinggemma), [developer guide](https://developers.googleblog.com/en/embeddinggemma-2-the-developer-guide/), [AI Edge post](https://developers.googleblog.com/en/google-ai-edge-with-embeddinggemma-2/)). No arXiv report found (API query empty); v1 paper is [arXiv:2509.20354](https://arxiv.org/abs/2509.20354).

| Item | Value | Source |
|---|---|---|
| Params | 740M = 270M text + 170M vision + 300M audio, **selectively loadable** from one checkpoint | [model card](https://huggingface.co/google/embeddinggemma-2), [config.json](https://huggingface.co/google/embeddinggemma-2/raw/main/config.json) |
| Space | one shared 768-d space for text/code/image/video/audio, interleavable; MRL truncation 512/256/128 (L2-renorm after slice); 8,192-token context; 100+ languages; mean-pooled + L2-normalized | card; [inference guide](https://ai.google.dev/gemma/docs/embeddinggemma/inference-embeddinggemma-with-sentence-transformers) |
| Single tower | "all inputs are processed through the shared backbone and their resulting embeddings occupy the same dimensional space"; a 270M-text query matches full-model documents directly; worked example: text "San Francisco" vs Golden Gate photo 0.641 | [developer guide](https://developers.googleblog.com/en/embeddinggemma-2-the-developer-guide/), [multimodal guide](https://ai.google.dev/gemma/docs/embeddinggemma/multimodal-embeddinggemma-with-sentence-transformers) |
| Token costs | image 280 default (budgets 70/140/280/560/1120); video 140/frame @1 fps (≤32 frames); audio 25 tok/s (≤327 s per input) → chunk everything | [processor_config.json](https://huggingface.co/google/embeddinggemma-2/raw/main/processor_config.json); card "Context Limits" |
| Precision | bf16/fp32 **only** — fp16 overflows → NaN/degraded | card "Numerical Precision" |
| Prompts | query `"task: search result \| query: "` (`SearchQuery`); doc `"title: none \| text: "`; media unprefixed; titles measurably help | [config_sentence_transformers.json](https://huggingface.co/google/embeddinggemma-2/raw/main/config_sentence_transformers.json); card |
| License | **Apache 2.0**, ungated (v1 was Gemma-terms, gated). Card still asks adherence to the [Gemma Prohibited Use Policy](https://ai.google.dev/gemma/prohibited_use_policy) as policy, not license | [HF API](https://huggingface.co/api/models/google/embeddinggemma-2); [docs](https://ai.google.dev/gemma/docs/embeddinggemma) |
| Quality | MTEB-ml 61.36; MTEB-code 78.68 (+9.92 over v1); MIEB-lite 64.64; MMEB-v2 image 57.28 Hit@1, video 50.67; ~95% quality at 256-d for image/video/speech retrieval | card benchmarks; developer guide |
| No reranker from Google | HF `author=google&search=rerank` is empty; Google's answer is 128-d shortlisting | [HF API](https://huggingface.co/api/models?author=google&search=rerank); developer guide |

Linux runtimes: **GGUF/llama.cpp** (official ggml-org auto-conversion, `llama serve -hf ggml-org/embeddinggemma-2-GGUF`; media encoders live in the mmproj file), **Ollama** tags `:270m/:440m/:570m/:740m` (image support over its embed API UNVERIFIED), **sentence-transformers ≥6.1.0** + transformers 5.x (official, needs torch; video via torchcodec), **LiteRT-LM** QAT bundles (int4 text/int8 vision, 485 MB full), **onnx-community ONNX** (browser demos). [ggml README](https://huggingface.co/ggml-org/embeddinggemma-2-GGUF/raw/main/README.md), [unsloth GGUF](https://huggingface.co/unsloth/embeddinggemma-2-GGUF), [LiteRT card](https://huggingface.co/litert-community/embeddinggemma-2-740m-litert-lm/raw/main/README.md), [ollama library](https://ollama.com/library/embeddinggemma-2), [onnx-community](https://huggingface.co/api/models?search=embeddinggemma-2).

Desktop-scale numbers (LiteRT QAT card; Google's own measurements): RTX 4090 GPU 23.9 ms/image and 7.6 ms text; x86 CPU 338 ms/image; process memory 310 MB text-only to ~811 MB full-GPU; 1M vectors at 768d fp32 ≈ 3.07 GB (≈1.5 GB bf16; 1 GB at 256-d); MediaPipe's ANN is "single-digit-ms" but irrelevant at our scale (brute force wins below ~1M). Pixel-class RAM: ~191 MB text-only / ~567 MB full quantized.

## 4. This host (measured 2026-10-11)

| Fact | Value |
|---|---|
| GPU / RAM / CPU | RTX 3060 12 GB (driver 610.57.04) / 31 GB / 12 cores |
| Disk | btrfs, 893 GB total, 338 GB free; `/home` ≈ **3.95 M files** (measured `find`) |
| Corpus (plocate DB counts) | ~90.3k images, ~4.4k videos, ~1.3k audio, ~105k text/md/txt-class docs, 910 PDFs |
| Installed and reusable | Quickshell 0.3.1, Hyprland 0.56.2, uv 0.12.19, ffmpeg 9.0.1, tesseract 5.5.3, ripgrep 15.1, sqlite 3.53 (FTS5), plocate, evince, mpv, imv, firefox |
| Missing, must install/build | ollama (packaged, `extra/ollama` 0.33.3), a llama.cpp build that knows `embedding_gemma2` (Arch `extra/llama-cpp` 0.4.0 packaging date vs the 2026-10-06 launch: UNVERIFIED — the spike decides), whisper not needed (no ASR in this design) |
| Existing plugin ecosystem | 15 plugins in `~/.config/omarchy/plugins`, including `radimsem.omaone` and `radimsem.workspaces`; `omarchy-plugin-catalog/-validate/-add` tooling exists |
| Prior conclusion reused | [fsearch note](2026-10-09-fsearch-macos-linux-portability.md): name search on Linux is already ~1–8 ms (plocate); the gap is content semantics, and a no-stat crawl of `~` takes 0.65 s — reconciliation is cheap |

Scale estimate (arithmetic on DigUp's measured entry sizes — photo 1.6 KB, PDF page 6 KB, hour of video 1–2 MB): ~90k images ≈ 140 MB, ~105k docs chunks ≈ 200–300 MB, ~4.4k videos (≈1 vector/shot + audio windows) ≈ 100–200 MB, plus FTS5 → **index well under 1 GB**, ~300–500k vectors → ~0.5–0.8 GB RAM for a full fp16 brute-force scan (page-cache-warm), single-digit-to-30 ms per query leg. First-pass indexing on GPU: ≈90k images at even 60–100 ms ≈ 1.5–2.5 h, text chunks ~1–2 h, video ~2–3 h → **one weekend afternoon**, or a CPU night at 338 ms/image ≈ 8–9 h.

## 5. Why a separate plugin and not an omaone feature

- [omaone ADR 0001](https://github.com/radimsem/omaone/blob/HEAD/docs/adr/0001-no-generative-model.md) says "omaone never asks a model to write text" and scopes the whole product to decision-model routing behind a Fuse. An embedding model is an encoder, not a generator, so nothing in the ADR's *letter* is violated — but the *product* fit is wrong: omaone's surfaces (Inbox, Field, Fuse, Machines) carry Session/Request semantics; a whole-drive content index shares no state, no IPC, and no UX with them.
- omaone's own AGENTS.md demands surgical, issue-scoped diffs and contracts (`docs/contracts.md` session ids, socket messages) — a 400 MB index daemon and a model downloader do not belong in that contract surface or its CI ("tests run offline and finish in milliseconds"; a GGUF downloader in tests breaks that).
- The valuable omaone assets transfer as **conventions, not code**: manifest `kinds` + `entryPoints`, one socket client (`Service.qml` is the only QML that talks to the helper), JSON-lines IPC over `$XDG_RUNTIME_DIR/<plugin>/ui.sock` (0700/0600, `SO_PEERCRED` UID check) per [docs/ipc.md](https://github.com/radimsem/omaone/blob/HEAD/docs/ipc.md), inline `shell.json` settings written only through `updateEntryInline`, Hyprland bindings inside an owned `-- <plugin>-shortcut-start/end` block, `bin/<plugin> setup/status` with documented exit codes, systemd user unit `PartOf=graphical-session.target` with `ConditionPathExists` on the manifest, helper venv at `~/.local/share/<plugin>/venv` locked with uv, no symlinks in the plugin folder (`omarchy plugin validate`), "ship nothing GPL or AGPL".

## 6. Everything the plugin must implement and cover

### 6.0 How the search works: two phases (why a directory-picker setup screen is required)

The single-tower model puts query and content in one 768-d space, which splits the work in two:

| Phase | What is embedded | Cost | When |
|---|---|---|---|
| **Index time (pre-computed)** | every segment of every file under the user-picked roots — image, PDF page, ~1800-char chunk, 30 s audio window, deduped video keyframe — as 768×fp16 blobs in SQLite | image 60–100 ms GPU / 338 ms CPU; text chunk ~10–20 ms; this host ≈ 1.5–3 h one-time first crawl | at setup, then per new/changed file via inotify (seconds) |
| **Query time (on the fly)** | only the natural-language query text, through the text-only encoder | ~10–20 ms GPU embed + few-ms brute-force scan | every Enter |

Nothing about the *content* is re-embedded at query time — doing so (90k images × 60–100 ms) would take hours per query, which is precisely what pre-embedding eliminates. DigUp follows the same rule: user picks folders, the watcher keeps them fresh, "no rescans" (comment `pf4bwaz`). Consequence for the UI: the **first-run setup screen is a directory picker** (§6.6), with file-level control handled by rules (`excludeDirs`, global secrets filter, `*.noindex`) — not by per-file checkboxes, which go stale as files move and fragment the watcher's scope.

### 6.1 Plugin mechanics (Omarchy contract)
- `manifest.json`: `schemaVersion: 1`, id `radimsem.omafind`, `kinds: ["service","bar-widget","panel"]` (bar widget optional later), entry points `Service.qml`/`Surface.qml`; passes `omarchy plugin validate` (no symlinks inside the folder; the dev checkout links *into* `~/.config/omarchy/plugins/` from outside, as omaone's README does).
- Summon API: Hyprland bind calling `omarchy-shell shell summon radimsem.omafind '{"view":"search"}'`; bindings live only in an owned `-- omafind-shortcut-start/end` block; `bin/omafind bindings check` mirrors omaone's conflict checker (`hyprctl binds -j`).
- Settings: camelCase keys inline in the plugin's `shell.json` entry; candidates: `roots` (XDG user-dirs default), `excludeDirs`, `indexCode`, `codeRoots`, `imageBudget` (70/140/280), `maxResults`, `keepModelLoaded`, `updateChecks`.
- Runtime: `omafindd` Python 3.12 helper (uv-locked) as systemd user unit; JSON-lines socket `$XDG_RUNTIME_DIR/omafindd/ui.sock`, peer-UID checked; QML stays thin (draws state, sends intents).

### 6.2 Model runtime and download
- Downloader pins `ggml-org/embeddinggemma-2-GGUF` @ `bfcd298…` with both sha256 digests (values in DigUp's `ModelFiles.swift`), resumes, and **rejects F16 files** (P4); stores under `~/.local/share/omafind/model/`.
- Embedder: small native `omafind-embed` (C++ over libllama, ≈DigUp's `LlamaEmbedder.swift` contract): JSON-lines in, base64 f32 vectors out; mean-pooled, L2-normalized 768-d; text-only mode = no mmproj (~0.25–0.31 GB); full mode text+vision(+audio) ≈1 GB; batches ≤16 seqs; image budgets {70…1120} with bicubic pre-resize; applies the no-logits patch rationale (262k-vocab logits waste). CUDA build, CPU fallback; `start-on-demand, exit-when-idle`.
- Gate: port `ReferenceVectorTests` — stored reference vectors for one photo, one speech clip, one screen render; any llama.cpp/model upgrade must reproduce cosine ≥ 0.999 against a one-time bf16 transformers reference on this GPU.

### 6.3 Ingestion, watching, lifecycle
- Roots: user-picked, default XDG `PICTURES/VIDEOS/MUSIC/DOCUMENTS/DOWNLOAD`; skip rules ported from [`Rules.swift`](https://github.com/ARahim3/DigUp/blob/HEAD/Sources/DigUpKit/Rules.swift): `*.noindex`, dot-dir/heavy-dir blocklist, secret extensions+names (`id_rsa`, `.env`, `.pem`, `.kdbx`, …) applied to **all** kinds at crawl time, dataset-folder skip (≥300 same-kind machine-named files), size caps.
- Crawler: parallel `os.scandir` walk (type from `d_type`; defer `stat` to per-file work); resume journal; `nice`/idle I/O priority; pause when on battery (`upower`).
- Watcher: `watchdog` inotify per-root recursive; on create/change compare (size, mtime); delete/prune; directory churn coalesced (DigUp waits ~1 min of quiet before re-indexing code); restart = reconcile dirty roots by re-walk (0.65 s for all of `~` per fsearch measurement — cheap).
- Limits & caps ported from `IndexOptions`: >50-page PDFs paginated in passes; hard caps 5k pages / 5k chunks per file; ≤1200 frames per video.

### 6.4 Extraction matrix on Linux (license-clean)

| Kind | Tool (all subprocess or BSD/Apache/MIT libs — no GPL/AGPL links) | Segments |
|---|---|---|
| image | `pillow` (MIT) decode/resize; `tesseract` CLI (Apache-2.0) for screenshot-ish images (name heuristics: `Screenshot`, `Screen Shot`, `screenshot-`… — no Linux xattr equivalent, [UNVERIFIED] GNOME/Deepin xattrs) | 1 image vector (budget 140; 280 for screenshots) + OCR → FTS5 only |
| pdf | `pypdf` (BSD) page text; `pypdfium2` (BSD, Apache-license wrapper over BSD PDFium) render pages with <200 chars → image vector | per page, `loc` = page |
| text/docs | encoding-tolerant read; `python-docx`/`odfpy` (BSD) for docx/odt; stdlib HTML tag-strip; markdown untouched | ~1800-char chunks, 200 overlap |
| spreadsheet/ppt | v1: names only (DigUp also does not read these) | — |
| audio | `ffmpeg` (LGPL build, system binary, subprocess) → 16 kHz mono PCM; RMS gate | 30 s windows, 25 s hop |
| video | `ffmpeg` frames every 3 s + 8×8 average-hash dedup (≈1/shot); soundtrack through the audio path | frame vectors (budget 70) + audio vectors, `loc` = start second |
| code | `git ls-files` per repo; skip generated/vendored by path+name rules | ≤1800-char line stretches; separate `code.sqlite`; `code:` prefix |

### 6.5 Storage and search
- One `index.sqlite` (WAL, `synchronous=NORMAL`) + separate `code.sqlite`; schema per [`IndexStore.swift`](https://github.com/ARahim3/DigUp/blob/HEAD/Sources/DigUpKit/IndexStore.swift): `files(path,kind,size,mtime,inode,state)`, `segments(kind,modality,loc,vec BLOB 768×fp16)`, `fts` FTS5 (name×3 bm25 weight, `porter unicode61 remove_diacritics 2`); vector-version column gates re-embedding on model change.
- Query: normalize → `SearchQuery` prompt → text-only embed (~10–20 ms GPU / ~70 ms CPU) → numpy fp16→fp32 block matmul vs mmap'd/all-loaded vectors → per-modality-centered z + 2·coverage^1.5 + kind hint; candidate gate; best-segment wins → result carries jump target.
- Fallbacks: model-load failure → keyword-only mode (FTS5 still useful) with a visible banner; disk-space guard; corrupt-db → rebuild.

### 6.6 UI (Quickshell QML, omaone design rules apply)
- Search panel surface (own `Surface.qml` + `SearchView.qml`): query field, per-kind grouped results with thumbnails (pre-extracted 128-px JPEG thumbs on disk, path in `files.info`), snippet with `«»`-style marks from FTS5, one row = one file showing the winning segment ("page 12", "14:32"), `Enter` jumps, `Ctrl Enter` reveals in thunar, `Ctrl C` copies path.
- Setup card (first run): pick roots, disk/RAM estimate, "Download model 865 MB" with progress, binding conflict check — omaone's SetupCard pattern.
- Progress: bar widget (optional v1.1) or toast for first-crawl progress ("indexed 41,203 / ~90,000").

### 6.7 Privacy and security (must-do, not optional)
- Global secrets filter at crawl (P12); `chmod 700` `~/.local/share/omafind`, 600 on db + model; index excluded from backups by living under a dot dir and honoring `*.noindex`.
- Thumbnails and stored text snippets are cleartext on disk — document the threat honestly (same class as DigUp's criticism `pf2rv4j`); optional SQLCipher later, never a silent default.
- No telemetry; update check opt-in (DigUp's toggleable Sparkle check is the model).
- Socket peer-UID check like omaone's `ipc.py`; never log file text.

### 6.8 Install, ops, tests, CI (clone omaone's bar)
- `bin/omafind setup` (venv, unit install/enable/start, model download), `status` (unit/socket/index counts/model presence; documented exit-code table), `search --json` (CLI = same engine, and the MCP/agent hook: herdr agents get content search for free), `bindings check`.
- Tests offline-first: fake embedder (fixed vectors) for fusion/ranking; pure-python extractors on fixture files; watcher tests in tmpdirs; the one online-gated test is the reference-vector parity suite (marked, manual). Evals: seed from [`evals/*.json`](https://github.com/ARahim3/DigUp/tree/HEAD/evals) + a personal corpus of ~300 files and ≥100 queries in English (+ the user's languages), tracked first-hit rate as the project's north-star metric (DigUp: 12/14 real-screenshot queries first).
- CI like omaone: ruff + pytest + `qmllint.sh`, ubuntu-latest, pinned actions; the GGUF build happens in the spike + tagged release artifacts, not CI.

### 6.9 Licensing (omaone rule: "ship nothing GPL or AGPL")

| Component | License | Verdict |
|---|---|---|
| EmbeddingGemma 2 weights (incl. ggml GGUFs) | Apache-2.0, ungated | ship with attribution + license copy (Apache §4) |
| llama.cpp + no-logits patch + schema/ranking port from DigUp | MIT | reuse with attribution (DigUp is MIT) |
| pypdf, pypdfium2, pillow, watchdog, numpy | BSD / MIT / Apache / Apache / BSD | clean |
| tesseract | Apache-2.0 | clean (PaddleOCR would drag GPL-adjacent deps — avoid) |
| ffmpeg, poppler-utils | LGPL / GPL system binaries, subprocess only | OK: not shipped, not linked; prefer pypdfium2 to keep PDF in-process |
| PyMuPDF | AGPL | **excluded** despite being the obvious PDF lib — pypdfium2 instead |
| torch (spike reference only) | BSD-3 | dev/spike only, never a runtime dep |

## 7. Strategic plan

### Phase 0 — Spike: "can this GPU embed?" (a day, throwaway script)
1. Get a llama.cpp that runs `embedding_gemma2`: try Arch `extra/llama-cpp`; else port `build-llama.sh` to Linux (cmake, `-DGGML_CUDA=ON -DLLAMA_BUILD_MTMD=ON`, no xcrun step), tag ≥b11452 (DigUp pins b11461). Record the minimum version actually needed (currently UNVERIFIED).
2. Embed 10 own photos + queries with the text file only, mmproj loaded for images; compute cosine table; compare against a one-time `sentence-transformers` bf16 run (uv script) — target parity ≥0.999, image embed ≤100 ms/img, text ≤20 ms.
3. Also try `ollama pull embeddinggemma-2:740m` and probe whether its embed API accepts images (UNVERIFIED today). Decide runtime: **embed-shim wins unless it stalls** (DigUp-validated lifecycle + minimal footprint); Ollama is the boring fallback.
4. Exit gate: text→photo query ranks the right photo first on a 20-query personal set; then commit to the project. Kill criterion: if GGUF CUDA embeds are broken and Ollama can't take images, park until upstream fixes (do not silently switch runtimes mid-project).

### Phase 1 — Engine as CLI (≈1 week)
Repo `omafind` scaffolded from omaone conventions (§6.1 skeleton, helper `omafindd`, lib/ JS only where QML logic needs tests). Deliverables: crawler + rules + extractors + index + fusion + `bin/omafind search --json`; eval harness + personal corpus results table. **Acceptance:** first-hit ≥90% on a 100-query personal eval; text query end-to-end <150 ms warm; secrets fixtures never indexed (test).

### Phase 2 — Service + freshness (≈1 week)
`omaoned` daemon (asyncio): queue, worker pool (extract+embed subprocess), inotify watcher, reconcile-on-start, resume journal, progress over the socket, jump-to-target (`evince --page`/`mpv --start`/`imv`/`xdg-open`). **Acceptance:** drop a file into `~/Pictures` → searchable in <5 s (mirrors DigUp's 1–2 s claim); kill -9 daemon → restart reconciles without full re-crawl; idle RSS (no model loaded) <60 MB.

### Phase 3 — Plugin surface (≈1 week)
QML search panel + setup card + bindings, per omaone DESIGN/canvas workflow (colors via `qs.Commons`, no hex in QML, grim screenshots beside the board). First-crawl progress UX. **Acceptance:** hotkey opens panel <100 ms after shell warm; results render with thumbs; Enter jumps correctly for all four modalities; `omarchy plugin validate` clean; installed from a clean clone via `omarchy plugin add … --enable`.

### Phase 4 — Hardening + release (few days)
Security pass against §6.7 (exclude dirs round-trip test, perms check in `status`); model file re-verification on start; multilingual eval if wanted (DigUp covers EN/Bengali/Arabic); packaging: model download mirror (HF + Kaggle), changelog, README, catalog submission (`omarchy-plugin-catalog`). Stretch, later: OpenAI-compatible embedding endpoint for LAN/agent reuse (DigUp plans the same, `pf4mrgw`), `omafind` MCP wrapper for herdr agents, video "moments" UI, at-rest encryption.

### Decision log (locked choices)

| Decision | Chosen | Rejected | Reason |
|---|---|---|---|
| Product home | own plugin | omaone view | §5 |
| Model | EG2 GGUF Q8_0 | CLIP+whisper+captioner chain; EG2-300m (no multimodal); API models | one space, Apache-2.0, offline, DigUp-validated |
| Runtime | llama.cpp/CUDA shim | sentence-transformers/torch runtime; LiteRT-LM; ONNX | torch = heavy dep + fp16 footgun risk; LiteRT image path on x86-GPU less proven for mtmd audio; shim matches DigUp parity-tested path. Ollama = documented fallback |
| Vectors | 768-d fp16 blobs, brute force | sqlite-vec/usrecall/FAISS/LanceDB; 128-d MRL | <500k vectors is ms-scale without infra; 128-d measurably degrades multimodal (MMEB 59→46) — 256-d is the later storage lever, not the default |
| Ranking | port DigUp fusion | RRF; raw cosine | their eval: 0.88 vs 0.73 R@1; cosine compression |
| ASR/captioner | none | whisper.cpp + text embeddings | single-tower cross-modal retrieval is the model's whole point (Edge post: "reduces … chaining separate … models") |
| Watcher | inotify/watchdog, `$HOME` scope | fanotify root daemon (fsearch PR #2 style) | root + `CAP_SYS_ADMIN` daemon fails omaone safety norms; user-dirs coverage is the product |
| Name search | plocate stays | reimplement | fsearch note §8 |

### Risks

| Risk | Evidence | Mitigation |
|---|---|---|
| llama.cpp CUDA/mmmd quality ≠ Metal (DigUp validated on Metal) | no published Linux numbers; UNVERIFIED | Phase 0 parity gate against bf16 reference; CPU fallback |
| Arch `llama-cpp` package predates `embedding_gemma2` support | package version 0.4.0 packaging date unknown | build script from pinned tag (DigUp's script minus xcrun) |
| fp16 silent degradation | card "Numerical Precision" | Q8_0 only; sha256 + F16 reject; reference-vector gate |
| Index is plaintext personal data | Reddit `pf2rv4j` | perms, global secrets filter, `*.noindex`, honest README; SQLCipher later |
| Screenshot detection gap (no `kMDItemIsScreenCapture`) | Mac-only xattr | name heuristics + OCR every image under a size/aspect heuristic; measure miss rate in eval |
| First-crawl noise (90k images ≈ hours) | 338 ms/img x86-CPU (LiteRT card) | GPU default; resumable journal; idle priority; progress UX |
| Upstream DigUp Linux port lands | OP committed (`pf5bph2`) | not a blocker: ours is QML/Omarchy-native, MIT attribution either way; consider upstreaming the ranking port |
| RTX 3060 contention with omaone local decider (both GPU-resident) | host has one GPU | embedder exits-when-idle (P10); never both loaded by design |

## 8. Reuse verbatim vs build fresh

- **Verbatim (MIT, attribute DigUp + pinned rev `6faa29e`):** index schema, fusion formulas and constants, chunk/window constants (1800/200, 30 s/25 s, 3 s frames, avg-hash ≤4 bits), prompt strings, secret/dataset rules, `evals/*.json` + `scripts/testbed` generation scripts, no-logits patch, reference-vector test idea.
- **Fresh:** inotify watcher, ffmpeg/pillow/tesseract/pypdf extractors, numpy scan, asyncio daemon + socket protocol, QML panel + setup, installer, jump-to-target, model downloader.
- **Fresh ADRs to write in the new repo:** ADR-1 "one embedding model, no generative models, no ASR/captioner chain" (mirrors omaone ADR-0001 spirit); ADR-2 "brute force over fp16 blobs until >1M segments"; ADR-3 "user-dirs scope, no root, no fanotify".

## 9. Unverified / open

- All DigUp performance and eval numbers: author-reported on M-series Macs, synthetic testbed; not reproduced (his evals do ship — reproducing them is part of Phase 1's cost).
- Ollama image-embedding API and per-tag sizes; exact minimum llama.cpp version; vLLM/SGLang claims from Google's blog only.
- No EmbeddingGemma 2 arXiv report (absence via API query only).
- Whether DigUp's shipped 0.6.0+ fixed the code-only secrets filter (thread said "getting fixed"; changelog unchecked).
- VectorDash (community Windows fork) quality; whether any Linux port of DigUp exists today.
- Arch `llama-cpp` 0.4.0 build date vs the 2026-10-06 model launch (decided by spike).
- Reddit facts come from the Arctic Shift mirror because reddit.com bot-walls anonymous readers; numbers (353 score / 179 comments) are archive snapshots.

## 10. Primary-source index

- Reddit thread: https://www.reddit.com/r/LocalLLaMA/comments/1x2eeds/ · mirror API: https://arctic-shift.photon-reddit.com/api/posts/ids?ids=1x2eeds , .../api/comments/search?link_id=1x2eeds
- DigUp: https://github.com/ARahim3/DigUp (HEAD `6faa29e`), API https://api.github.com/repos/ARahim3/DigUp (+ /languages /releases /contributors); key files under https://raw.githubusercontent.com/ARahim3/DigUp/HEAD/ — README.md, scripts/build-llama.sh, scripts/llama.cpp-no-logits.patch, Sources/DigUpKit/{Model,ModelFiles,IndexStore,Database,Searcher,SearchText,Crawler,Rules,Indexer,Extractors,MediaExtractors,CodeExtractor}.swift, Sources/LlamaRuntime/LlamaEmbedder.swift, Tests/LlamaRuntimeTests/ReferenceVectorTests.swift, worker/pyproject.toml, evals/*.json
- EmbeddingGemma 2: https://huggingface.co/google/embeddinggemma-2 (+ /raw/main/config.json, /raw/main/processor_config.json, /raw/main/config_sentence_transformers.json); https://huggingface.co/ggml-org/embeddinggemma-2-GGUF ; https://huggingface.co/unsloth/embeddinggemma-2-GGUF ; https://huggingface.co/litert-community/embeddinggemma-2-740m-litert-lm ; https://ollama.com/library/embeddinggemma-2 ; https://blog.google/innovation-and-ai/technology/developers-tools/embeddinggemma-2/ ; https://ai.google.dev/gemma/docs/embeddinggemma (+ /model_card_2, /inference-embeddinggemma-with-sentence-transformers, /multimodal-embeddinggemma-with-sentence-transformers) ; https://developers.googleblog.com/en/embeddinggemma-2-the-developer-guide/ ; https://developers.googleblog.com/en/google-ai-edge-with-embeddinggemma-2/ ; v1: https://huggingface.co/google/embeddinggemma-300m , https://arxiv.org/abs/2509.20354
- omaone conventions: local `/home/radimsem/personal/projects/omaone` — AGENTS.md, manifest.json, docs/adr/0001-no-generative-model.md, docs/ipc.md, docs/contracts.md, systemd/omaone.service, README.md
- Related notes: [2026-10-09-fsearch-macos-linux-portability.md](2026-10-09-fsearch-macos-linux-portability.md); session artifacts `local://digup-findings.md`, `local://embeddinggemma2-findings.md`
