# omafind design

Date: 2026-10-11. Status: approved in brainstorming, awaiting spec review.
Source research: [docs/research/2026-10-11-digup-embeddinggemma2-omarchy-content-search-strategy.md](../../research/2026-10-11-digup-embeddinggemma2-omarchy-content-search-strategy.md). Where this spec and the research note disagree, this spec wins. Section 10 lists the corrections.

## 1. Intent

**What the user said**
- v1 is a personal tool. It must work very well on this host (RTX 3060 12 GB, 31 GB RAM, LUKS-encrypted btrfs) and on the user's own files. Catalog submission and other users' hardware come later.
- Success: the user reaches for omafind every day instead of digging through folders.
- The corpus is the XDG user dirs, other directories the user picks, and removable external drives.
- Setup must scan the drive, count text, image, video and audio files, and propose candidate parent directories. The user edits that list before indexing.
- All four modalities ship in v1: text and PDF, images with OCR, video frames, and audio.
- The search surface is an Omarchy overlay laid out like DigUp's macOS window: a grouped result list on the left and a detail pane for the selected result on the right (7.1). The approved mockups are the design canvas https://claude.ai/artifact/VPwvi2kmd8oRpCqmdjUAXt.
- Code search ships in v1, opt-in per repository, behind the `code:` prefix.
- The repo is GitHub `radimsem/omafind`, private for now.

**Assumptions** (confirmed in brainstorming or stated without objection)
- omafind is a separate plugin, not part of omaone, and shares no state or IPC with it.
- The `search --json` CLI ships in v1 because it costs almost nothing and gives herdr agents content search.

**Out of scope for v1**: whole-disk filename search (plocate covers it), spreadsheets and presentations beyond their names, at-rest encryption beyond LUKS, a bar widget, an MCP wrapper, and any network access other than the model download and the runtime build.

## 2. Architecture

```
Hyprland bind / omarchy-menu row
        │ omarchy-shell shell summon radimsem.omafind '{"view":"search"}'
        ▼
┌─ Quickshell plugin (thin) ───────────────┐
│ Service.qml  only socket client          │
│ Overlay.qml  views: search | setup       │
│ lib/*.js     protocol, reducer, grouping │
└──────────────┬───────────────────────────┘
               │ JSON-lines over $XDG_RUNTIME_DIR/omafind/ui.sock (0600, peer-UID check)
┌──────────────▼───────────────────────────┐
│ omafindd: Python 3.12, uv-locked, asyncio, systemd user unit
│ discovery · rules · crawler · watcher · volumes
│ extractors/{text,pdf,image,video,audio} · jobs + journal
│ store (one SQLite per volume) · search (fusion) · embedder
└──────────────┬───────────────────────────┘
               │ HTTP POST /v1/embeddings on loopback, random API key per spawn
┌──────────────▼───────────────────────────┐
│ llama-server, pinned llama.cpp tag ≥ b11461, Vulkan build, spawned on demand
│  text mode: model only (~0.3 GB), for queries
│  full mode: model + mmproj (~0.9 GB), for indexing
└──────────────────────────────────────────┘
```

### 2.1 Units

| Unit | Responsibility | Depends on |
|---|---|---|
| `Service.qml` | Owns the socket and all plugin state. Sends intents, draws state. The only QML that talks to the daemon. | `lib/Protocol.js`, `lib/Connection.js`, `lib/Backoff.js` |
| `Overlay.qml` + views | Search view and setup view. No logic beyond layout and key handling. | `Service.qml`, `lib/results.js` |
| `lib/*.js` | Pure functions: message encode/decode, connection reducer, result grouping, settings merge and clamp. | none |
| `omafindd.ipc` | Socket server, hello handshake, dispatch, events. | all daemon units through narrow calls |
| `omafindd.discovery` | Lists `$HOME` and mounted volumes with `fd`, counts kinds per directory, proposes candidates. | `rules`, `fd`, `lsblk` |
| `omafindd.rules` | Global skip rules (4.3): one glob list rendered as `fd` arguments, plus the dataset and size-cap post-filters and the per-rule counts for the boards. | `fd` |
| `omafindd.crawler` | Runs `fd` on each selected root and upserts `files` rows as pending. | `rules`, `store`, `fd` |
| `omafindd.watcher` | inotify on internal-volume roots, coalesces churn, re-lists changed directories with `fd` from the root, marks files pending or deleted. | `rules`, `store`, `watchdog` |
| `omafindd.volumes` | Maps paths to volume UUIDs, watches mounts, announces new and returning drives. | `findmnt`, `lsblk` |
| `omafindd.extractors.*` | Turn one file into segments (text chunks, page renders, frames, audio windows), plus FTS text and a thumbnail. Pure, run in a process pool. | `pdfinfo`, `pdftotext`, `pdftoppm`, `magick`, `ffmpeg`, `ffprobe`, `tesseract`, stdlib `zipfile` |
| `omafindd.embedder` | Starts, stops and talks to llama-server. Validates vectors. Chooses GPU or CPU. | `runtime/bin/llama-server`, `model/*.gguf`, `nvidia-smi` |
| `omafindd.jobs` | Bounded queue, worker pool, resume journal, progress events. | `extractors`, `embedder`, `store` |
| `omafindd.store` | One SQLite file per volume plus `code.sqlite`: schema, migrations, transactions, vector loading. | sqlite3 |
| `omafindd.search` | Query parsing, both legs, fusion, jump targets. The `code:` words leg runs `rg`. | `embedder`, `store`, `rg` |
| `omafindd.opener` | Turns a result into the right opener command for the jump target. | `omarchy-launch-editor`, `omarchy-launch-browser`, `mpv`, `xdg-open`, `gdbus` |
| `bin/omafind` | `setup`, `status [--json]`, `discover --json`, `search --json`, `reindex`, `bindings check`, `build-runtime`. Stdlib only, imports daemon modules for shared logic. | daemon modules |

### 2.2 Repo layout

The plugin root is the repo root, as in omaone. No symlinks inside it; the dev checkout is linked into `~/.config/omarchy/plugins/radimsem.omafind` from outside.

```
manifest.json            kinds ["service","overlay"], keepLoaded true
qmldir  Service.qml  Overlay.qml  SearchView.qml  SetupView.qml  ui/
lib/                     .pragma library JS, tested with node --test
helper/pyproject.toml    hatchling, requires-python >=3.12, uv.lock committed
helper/omafindd/         python -m omafindd
bin/omafind
systemd/omafind.service
scripts/build-runtime.sh scripts/qmllint.sh
tests/{helper,js,fixtures,fakes}
docs/{contracts.md,ipc.md,DESIGN.md,adr/,research/,superpowers/specs/}
evals/
```

### 2.3 On-disk state

Everything lives under `~/.local/share/omafind/`, mode 0700:

| Path | Content |
|---|---|
| `venv/` | uv environment (`UV_PROJECT_ENVIRONMENT`) |
| `runtime/bin/llama-server` | pinned build from `scripts/build-runtime.sh` |
| `model/embeddinggemma-2-Q8_0.gguf`, `model/mmproj-embeddinggemma-2-Q8_0.gguf` | sha256-verified, mode 0600 |
| `index/<volume-uuid>.sqlite` | one DB per volume, mode 0600 |
| `index/code.sqlite` | the code index, mode 0600, only when a code repository is selected |
| `thumbs/<volume-uuid>/` | 128 px JPEG thumbnails |
| `journal` | in-flight file ids for crash recovery |

The index of an external drive lives on the internal disk, not on the drive.

### 2.4 Lifecycle

- The daemon runs as `omafind.service` (systemd user unit, `PartOf=graphical-session.target`, `ConditionPathExists` on the manifest, `NoNewPrivileges=true`). It loads no model at idle. Target idle RSS is under 60 MB, excluding the vector matrix.
- When the overlay opens, `Service.qml` sends `warm`. The daemon starts a text-mode llama-server so the first query does not pay the load time. The server stops after 5 minutes without a query.
- Indexing starts a full-mode llama-server only while the queue is not empty. The server stops when the queue drains.
- GPU policy: the daemon reads free VRAM with `nvidia-smi` before it starts a server. Full mode uses the GPU when at least 1.5 GB is free, otherwise it runs on CPU (`-ngl 0`) under `nice 19`. Text mode uses the GPU when at least 0.5 GB is free. If `nvidia-smi` fails, the daemon tries the GPU and falls back to CPU when the start fails. This lets omafind run beside omaone's local decider (about 9.5 GB when pinned).
- One server process at a time. A query while full mode is running uses the full-mode server.

### 2.5 External tools

omafind drives existing command-line tools instead of reimplementing them or linking Python decoders (ADR-5). Each tool is required, and each job has one code path.

| Tool | Package | Used for |
|---|---|---|
| `fd` 10 or newer | `fd` | discovery, crawl and watcher re-checks, `.gitignore` and `.ignore` handling |
| `rg` | `ripgrep` | the `code:` words leg, `open_line`, preview hit lines |
| `magick` | `imagemagick` | image orientation, the Catrom pre-resize (5.3), thumbnails |
| `pdfinfo`, `pdftotext`, `pdftoppm` | `poppler` | PDF page count, page text, page renders |
| `ffmpeg`, `ffprobe` | `ffmpeg` | video frames, audio PCM, stream probe |
| `tesseract` | `tesseract`, `tesseract-data-eng` | screenshot OCR |
| `git` | `git` | `git ls-files` for code roots |
| `findmnt`, `lsblk` | `util-linux` | volume identity, mount events, drive facts |
| `mpv` | `mpv` | audio and video jumps |
| `gdbus` | `glib2` | Show in folder |

Omarchy installs all of them except `poppler`, which arrives only as a dependency of other packages. `bin/omafind setup` and `status --json` report a `tools` check. When a tool is missing they print one `sudo pacman -S --needed <packages>` line and exit 1. plocate is not used: its database is up to a day old and prunes `/media` and `/mnt`.

## 3. Runtime and model

- **Runtime**: stock `llama-server` from a pinned llama.cpp tag, at least b11461 (b11452 is the first tag with `gemma-embedding2`). `scripts/build-runtime.sh` builds it with `-DGGML_VULKAN=ON -DLLAMA_BUILD_SERVER=ON`, Release, everything else off, into `runtime/`. It needs `vulkan-headers` and `shaderc`. Arch `extra/llama-cpp` (0.6.0) is too old and is not used.
- **Model**: `ggml-org/embeddinggemma-2-GGUF` at revision `bfcd298762cc34d0357ece5ebdd31791a3a374d8`.

  | File | Bytes | sha256 |
  |---|---|---|
  | `embeddinggemma-2-Q8_0.gguf` | 309,855,456 | `2188ac1deca4b77dffefd603c2776a9d76d9d74ec01841392982ebb840b09135` |
  | `mmproj-embeddinggemma-2-Q8_0.gguf` | 554,821,024 | `c4a8a52691ecef40618438928bdf9e68379b854e24166f292592353db0aab64f` |

  The downloader resumes, verifies both digests, and refuses any file with `F16` in its name. fp16 activations overflow in this model and produce NaN or degraded vectors.
- **Embedding contract**:
  - Only `POST /v1/embeddings` with typed content parts (`text`, `image_url` with a data URL, `input_audio`). Never the legacy `/embedding` route: with `image_data` it silently returns a text-only vector.
  - Prompts: queries use `"task: search result | query: <q>"`. Text documents use `"title: <file name> | text: <chunk>"`. Media is sent without a prefix.
  - Batches of at most 16 inputs.
  - Every returned vector must be 768-d, all finite, with L2 norm within 1e-3 of 1. A failing vector fails its file with `detail = "embedding precision fault"`.
  - Stored as 768 × float16 after L2 normalization.
- **Version gate**: each DB stores `model_rev` and `runtime_tag` in `meta`. A mismatch at start marks all segments of that DB for re-embedding.
- **ADR-4** records the choice of stock llama-server over DigUp's custom libllama shim, and the condition for revisiting it (section 9, spike).

## 4. Setup, discovery, roots and volumes

### 4.1 Setup flow

The setup view in the overlay, mirrored by `bin/omafind setup` and `bin/omafind discover --json`:

1. **Runtime and model.** Build llama-server if it is missing. Download both model files with progress. The view shows the disk cost: about 865 MB for the model and about 200 MB for the runtime.
2. **Discovery scan.** One `fd` listing of `$HOME` and of every mounted non-system volume from `lsblk -J`, with the global skip rules (4.3) as `fd` arguments. Nothing is `stat`ed: kind comes from the extension. Extra `fd` passes count what each rule removed (`dot`, `heavy`, `secrets`) for the boards, by name only. On this host `fd` lists all 3.9 M files under `$HOME` in 1.6 s, against 48 s for a serial `os.scandir` walk (the walk ran first, so `fd` had a warm cache), and the six text and PDF extensions with the default rules in 0.16 s. Each directory gets counts of `{text, pdf, image, video, audio}`, rolled up to its ancestors.
3. **Candidate list.** A candidate is a directory whose subtree holds at least 20 content files and that is the highest ancestor still dense in content. Rule: walk up from each dense directory and stop before an ancestor where the dense subtree holds less than 60% of the ancestor's content files. `$HOME` and volume roots are never proposed. XDG user dirs that hold content are pre-checked. Other candidates start unchecked. Each row shows the path, per-kind counts, estimated index size and estimated time. Estimates use per-kind rates measured in the spike.
4. **Code repositories.** A separate section lists git repositories found during the walk (a directory holding `.git`). All start unchecked. A checked repository goes to the code index (5.2), not the content index, and is searched only with the `code:` prefix.
5. **Edit.** The user checks or unchecks rows, adds any directory through a picker, and adds excludes per root. The view shows the total estimated time and size. **Start indexing** writes the roots to the plugin's `shell.json` entry and starts the crawl.
6. **Left out.** A root with excludes expands into a nested "left out" ledger in the same table (board 11). Each entry is a row with the per-kind counts it removes, shown as negative numbers, and no index size or time, since nothing is indexed. A header row sums the entries, and the root's own counts are net of them. Each entry is tagged with the rule that produced it, and its second line lists that rule's evidence as fact tokens (7.4):
   - `user`: an exclude the user added. Evidence: `added`, `files`. An X button includes it again.
   - `generated`: a subfolder whose file names match one machine-made pattern but stay under the dataset threshold in 4.3. Evidence: `pattern`, `match` (matching/total), `dataset limit`. Pre-applied; an X includes it again.
   - `no-kind`: a subfolder with no file of a searchable kind. Evidence: `files`, the extension histogram, `searchable 0`. Every count column is 0, so leaving it out visibly changes nothing.
   - `secrets`: the secrets rule (4.3) for this root, written as `<root>/**`. Evidence: matched extensions and the directories they sit in. It has a lock instead of an X and cannot be removed.
7. **Leave out a subfolder.** The filter button on a root, or the "Leave out a subfolder" row, opens a tree of that root's scanned subfolders (board 11b). Every node shows per-kind counts, a bar whose segments give the mix and whose length grows with the file count (log scale), index size and time. Unchecking a node leaves it out; a partly excluded parent shows a mixed checkbox. "Select by rule" picks every `no-kind` or `generated` folder at once. Ctrl Z undoes the last change. A footer ledger shows found, left out and kept files for the root.

### 4.2 Settings

Inline on the plugin's entry in `~/.config/omarchy/shell.json`, written only by the plugin through `updateEntryInline`, read by the daemon by mtime. Every key lands in `settings.example.json`, `settings.py`, `lib/Settings.js` and the README table in one change.

| Key | Type | Default |
|---|---|---|
| `setupDone` | bool | `false` |
| `roots` | `[{path, volume, excludes: [path]}]` | `[]` |
| `maxResults` | int, 10..200 | `40` |
| `codeRoots` | `[path]`, git repositories | `[]` |
| `warmMinutes` | int, 0..60 | `5` |
| `gpu` | `"auto"`, `"never"` | `"auto"` |
| `imageBudget` | 70, 140, 280 | `140` |
| `audio` | bool | `true` (forced off if the spike fails, see 5.3) |
| `shortcut` | string | `"SUPER + E"` |

### 4.3 Global skip rules

Applied to every kind at discovery, crawl and watch time:

A path is indexable when `fd` with the rule arguments lists it and the Python post-filters keep it. Discovery, the crawler and the watcher all use this one predicate.

- dot-files and dot-dirs: `fd` default
- inside git repos, files ignored by `.gitignore`: `fd` default, including parent repositories
- patterns in `.ignore` files: `fd` default. A `.ignore` holding `*` leaves its folder out, and `rg` honors the same file. This replaces the `*.noindex` marker.
- heavy dirs: `node_modules`, `.git`, `target`, `build`, `dist`, `venv`, `.venv`, `__pycache__`, cache dirs, as `-E` globs
- secrets: DigUp's `Rules.isSecret` list (`.pem`, `.key`, `.p12`, `id_rsa*`, `.env*`, `secret*`, `credential*`, `.netrc`, `.npmrc`, …) plus `.kdbx`, `.gpg`, `.age`, as `-E` globs, so omafind never sees these paths
- per-root excludes, as `-E` globs
- dataset folders: at least 300 files of one kind with machine-made names, a Python post-filter over the listing
- size caps per kind, a Python post-filter after `stat`

DigUp applies its secrets list to code only. omafind applies it everywhere. A test proves that a fixture tree of secrets never reaches `files`.

### 4.4 Volumes

- The internal disk is one volume, keyed by its filesystem UUID.
- Each external drive is a volume keyed by its filesystem UUID, with its own DB and thumbnail dir. Paths in a DB are relative to the volume's mount point, so a drive mounted at another path still matches.
- The daemon reads mount and unmount events from `findmnt --poll`, and the label, filesystem, size and removable flag of a drive from `lsblk -J -o UUID,LABEL,FSTYPE,SIZE,RM,HOTPLUG,MOUNTPOINTS`.
- When a known volume appears, the daemon reconciles its DB with a size and mtime walk.
- When an unknown volume appears, the daemon sends a toast: "New drive Photos2024 found. Scan it for content?" Accepting opens the setup view with candidates for that drive only.
- Removable volumes get no inotify watches. They update only through the reconcile on mount.
- When a volume is offline, its results still appear, marked `offline · <label>`. Enter on such a result shows "Photos2024 is not connected. Connect it to open this file."

### 4.5 Freshness on the internal volume

- `watchdog` inotify watchers on each selected root.
- Bursts in one directory are coalesced for 2 s. Then one `fd` call with the rule arguments lists the root again, filtered with `--full-path` to the changed directories, so the watcher and the crawler cannot disagree. Starting `fd` inside the changed directory is wrong: it does not check whether that directory itself is ignored by a parent `.gitignore`. Listed files compare (size, mtime) with the stored row. Rows no longer listed are deleted with their segments.
- On daemon start, roots marked dirty in the journal, or all roots after a crash, are reconciled by a re-walk.

## 5. Indexing pipeline

### 5.1 Flow

crawler or watcher → `files` row with `state = pending` → bounded asyncio queue → extract in a process pool → embed in batches → one transaction writes segments, FTS rows and the thumbnail path → `state` becomes `done`, `partial`, `skipped` or `failed` with a `detail`.

- The journal holds in-flight file ids. A `kill -9` loses at most one batch, which is retried on start. The walk keeps no journal: a rerun of `fd` is cheap.
- Workers run with `nice 19` and `ionice -c 3`.
- Progress events go to the plugin at most twice per second: done count, queued count, current volume.

### 5.2 Extractors

No GPL or AGPL library is linked. GPL or LGPL tools run only as subprocesses (`ffmpeg`, poppler). PyMuPDF is excluded (AGPL). Tools decode and resize; Python keeps the logic DigUp tuned (thresholds, windows, hashes, chunking).

| Kind | Tool | Segments | Extra |
|---|---|---|---|
| text: md, txt, html, docx, odt | stdlib; docx and odt through `zipfile` reading `word/document.xml` and `content.xml` | 1800-character chunks, 200 overlap, at most 5000 per file, `loc` = start line | full text into FTS5 |
| pdf | `pdfinfo` for the page count, one `pdftotext -f a -l b` call per pass with pages split at form feeds, `pdftoppm -scale-to 1024` then the `magick` pre-resize for pages with under 200 characters. An encrypted file fails with detail `encrypted-pdf` | one vector per page, `loc` = page; rendered pages are embedded as images | over 50 pages: first 30 in the first pass, the rest later; at most 5000 pages |
| image | `magick -auto-orient`, the Catrom pre-resize, `magick -thumbnail` | one vector per image, budget `imageBudget` (280 for screenshots) | 128 px JPEG thumbnail; OCR with `tesseract` into FTS5 only, for screenshot-like images (name pattern, or dimensions matching a common screen size) |
| video | `ffprobe` for streams; `ffmpeg` samples a frame every 3 s as 8 × 8 gray bytes, Python keeps a frame when its average hash differs by more than 4 bits, at most 1200 frames, and a second `ffmpeg` pass extracts kept frames at a 1024 px long side | frame vectors at budget 70, `loc` = second | soundtrack goes through the audio path; thumbnail is the first kept frame |
| audio | `ffprobe` for an audio stream, `ffmpeg` streams 16 kHz mono PCM, numpy RMS silence gate | 30 s windows, 25 s hop, `loc` = start second | none |
| code | `git ls-files` per repository in `codeRoots`, minus secrets, generated and vendored files (DigUp's `CodeExtractor` rules) | stretches of whole lines up to 1800 characters, `loc` = first line, `loc_end` = last line, stored in `code.sqlite` | no FTS table: the words leg runs `rg` over `codeRoots` live (6.3); queried only with `code:` |

Images sent to the server are pre-resized to the pixel area of their token budget. This guards against llama.cpp issue #30195, where the server ignores the configured vision budget. Every image, frame and rendered page goes through the one `magick -filter Catrom` resize that passed parity in 5.3; Pillow's resize was not measured and is not used.

### 5.3 Spike-gated items

Phase 0 decides these. The outcome is recorded in this spec and in ADR-4 before Phase 1 starts.

- **Audio through llama-server.** Documented upstream, not confirmed working. If it fails, `audio` is forced off, the audio and soundtrack legs are skipped, and the custom mtmd shim is reconsidered for media only.
- **Image parity.** Cosine at least 0.999 against a one-time bf16 sentence-transformers reference (transformers ≥ 5.19.0) for a photo, a screenshot, a rendered PDF page and, if audio works, a speech clip. These reference vectors become the regression gate for any runtime or model change.
- **Rates.** Measured per-kind times on GPU and CPU feed the setup estimates.

**Phase 0 outcome (2026-10-12, llama.cpp b11461 `4d756bc` with the no-logits patch, RTX 3060, Vulkan).** Full numbers are in ADR-4.

- **Audio works** through `input_audio`: cosine 0.99975 on the speech clip, so `audio` stays available. 30 s of audio is 754 prompt tokens.
- **Image parity holds** at cosine at least 0.99914 for every input (photo 140 and 280, frame 70, screenshot, PDF page). It requires the client pre-resize: the server's own downscale gives 0.986 to 0.993. The budget is a server-wide flag, not a request field. The client resizes with ImageMagick `-filter Catrom` to multiples of 48 with at most `budget * 2304` pixels, and the server runs with `--image-min-tokens 1` so a 63-token frame is not upscaled again. One server serves every budget.
- **Token budget.** Without a flag the server sends a 4000 px photo as 976 tokens. With `--image-max-tokens` 70, 140 or 280 it sends 67, 134 or 270, so the flag is honored at this tag. The pre-resize stays because of the parity result above.
- **Rates** per item on GPU / `-ngl 0`: text chunk 0.03 / 0.09 s, image (140) 0.10 / 1.4 s, frame (70) 0.05 / 0.7 s, 30 s audio 0.14 / 1.4 s.
- **Phase 0 query set:** not run. `~/Pictures` holds only screenshots, so `evals/phase0.json` has no pairs yet.

## 6. Storage and search

### 6.1 Schema

DigUp's `user_version 5` schema, reused under MIT with attribution (DigUp at `6faa29e`), with one added column and three added `meta` keys:

```sql
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- meta keys: model_rev, runtime_tag, volume_uuid, volume_label
CREATE TABLE files(id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
  size INTEGER NOT NULL, mtime REAL NOT NULL, inode INTEGER NOT NULL, device INTEGER NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending', detail TEXT, info TEXT, indexed_at REAL);
CREATE INDEX files_inode ON files(device, inode);
CREATE INDEX files_state ON files(state, kind);
CREATE TABLE segments(id INTEGER PRIMARY KEY, file INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, modality TEXT NOT NULL, loc REAL, loc_end REAL, excerpt TEXT, vec BLOB);
CREATE INDEX segments_file ON segments(file);
CREATE VIRTUAL TABLE fts USING fts5(name, body, original UNINDEXED,
  tokenize = "porter unicode61 remove_diacritics 2 categories 'L* N* Co M*'");
```

`files.path` is relative to the volume mount point. `info` is JSON (thumbnail path, page count, duration). Pragmas: WAL, `synchronous=NORMAL`, `foreign_keys=ON`. FTS5 BM25 weights: 3.0 for name, 1.0 for body. OCR text goes into `body` and gets no vector. `code.sqlite` has the same tables except `fts`: the `code:` words leg reads the files live with `rg`.

### 6.2 Vector scan

- On start, the daemon loads the `vec` blobs of every online volume into one numpy float16 matrix, with parallel arrays for segment id, file id, modality and volume.
- An offline volume's vectors are loaded on its first query and then kept.
- New segments are appended. Deleted ones are tombstoned and compacted when the daemon is idle.
- A query converts blocks to float32 and multiplies by the query vector. Brute force stays the design until more than 1M segments (ADR-2).

### 6.3 Query

1. Normalize the query. Parse an optional prefix: `img:`, `pdf:`, `vid:`, `aud:`, `doc:`, `code:`. A kind prefix filters to that kind. `code:` searches `code.sqlite` only; no other query touches it.
2. Run both legs in parallel:
   - **meaning**: embed the query with the search prompt, score every loaded vector.
   - **words**: FTS5 match, up to 100 files, giving each file's coverage = share of query words it contains. For `code:` the words leg is `rg --json -F -i -e <word>…` over `codeRoots`, which honors `.gitignore`. Coverage comes from the submatches of each file, the snippet from its first matching line.
3. Fuse, as DigUp's `Searcher.swift` does:
   - subtract each modality's mean cosine (a modality with fewer than 20 vectors uses the global mean), then compute one global z-score with a deviation floor of 0.02
   - lookup queries (identifier-like or quoted terms) use weights (meaning 0.5, words 4); others use (1, 2)
   - `score = wMeaning · max(z, 0) + wWords · coverage^1.5 + (1 if the file's kind is hinted)`
   - a file is a candidate when its best z ≥ 2 or its coverage ≥ 0.5
   - a file's best segment gives its `loc`, which is the jump target
   - hits below 0.5 × the top score go into a "weaker matches" group
4. Return the top `maxResults`, grouped into sections by kind. The section holding the top hit comes first; the other sections follow in order of their best hit; inside a section, results keep score order. Each result carries path, volume, online flag, kind, `loc`, an FTS snippet with match marks, and the thumbnail path.

### 6.4 Search as you type

- The words leg runs on every keystroke after a 50 ms debounce, so names and exact words appear at once.
- The meaning leg runs after 200 ms without typing and re-ranks the list in place.
- Each query carries a sequence id. Responses for an older id are dropped.

### 6.5 Degraded modes

- Model or runtime missing or failing: search runs words-only, with a one-line banner: "Semantic search unavailable: <reason>. Showing keyword matches."
- Disk space under 2 GB free: indexing pauses, with a banner that says so and how much is needed.
- A DB that fails `PRAGMA integrity_check` is moved aside and rebuilt by a re-walk.

## 7. Overlay and jump

### 7.1 Overlay

`Overlay.qml`, kind `overlay`, `keepLoaded: true`, modeled on Omarchy's first-party emojis and clipboard overlays. Colors and spacing come only from `qs.Commons` (`Color.menu.*`, `Style.*`). No hex values in QML.

Layout, as on the design canvas (boards 1 to 9):

- A query field at the top. `code:` swaps the search icon for a code icon.
- **Left pane**: results in sections by kind (Images, Video, Audio, PDFs, Documents, Code), ordered as in 6.3. Each row has a 44 px thumbnail or kind icon, the file name, and the folder; a keyword hit shows its snippet with the words in bold instead of the folder. A badge shows the jump target (`14:32`, `p. 12`, `L41`, `L1–47`) or `offline`. Hits below half the top score fold into a "› N weaker matches" row. The top hit is selected on every new result set.
- **Right pane**: the selected result, rendered by kind, then its name, folder, a meta line (kind, date, dimensions or duration or pages or lines, size), a why line of fact tokens (7.4), and actions.

  | Kind | Rendering | Why line | Primary action |
  |---|---|---|---|
  | image | the image, fitted | `leg meaning · part image · z 3.4` | Open |
  | video | the matched frame, play button, timestamp chip, scrubber with match markers | `leg meaning · part frame + speech · at 0:42 · z 3.1` | Open at 0:42 |
  | audio | player card: waveform, play button, progress bar with the matched 30 s window, "7:55 – 8:25 of 13:43" | `leg meaning · part audio · at 7:55–8:25 · z 2.7` | Open at 7:55 |
  | pdf | the matched page rendered, matched words highlighted, page chip | `leg words · part text · at p. 12 · hits …`, with the quoted snippet under it | Open at page 12 |
  | text | text excerpt with line numbers, hit lines highlighted, line-range chip | `leg meaning + words · part text · at L205–222 · z 3.2` | Open in <editor> at line 212 |
  | code | code excerpt with line numbers, hit lines and words highlighted, line-range chip | `leg meaning + words · part code · at L1–47 · hits … · z 2.9` | Open in <editor> at line 8 |

  Secondary action: Show in folder. Offline results show the cached thumbnail dimmed, the line "<label> is not connected. Connect it to open this file.", Open disabled and Copy path enabled.
- `Ctrl Space` plays or pauses audio and video inside the preview from the matched second, through `mpv` with no window (audio) or a Quickshell video item (video); the spike confirms which.
- Keys: arrows or `Ctrl J` / `Ctrl K` move across sections, `Enter` opens at the match, `Ctrl Enter` reveals the file in Nautilus through `org.freedesktop.FileManager1.ShowItems`, `Ctrl C` copies the path, `Esc` clears the query, then closes.
- Footer: the result count ("17 results · 3 weaker", "4 results in your code · 5 weaker", "Matching words…" while only the words leg has answered), key hints, and, with no query, indexing progress, watched folders and offline volumes.
- With no query the panes are replaced by a short explanation and prefix chips (board 8).
- The setup view (4.1) is a second view in the same overlay, opened with `{"view":"setup"}` and shown automatically while `setupDone` is false.

### 7.2 Entry points

- An owned block in the Hyprland bindings between `-- omafind-shortcut-start` and `-- omafind-shortcut-end`, written only when the user confirms in setup, default `SUPER + E`. Omarchy 4 already binds `SUPER + SHIFT + SPACE` (toggle top bar), `SUPER + SPACE`, `SUPER + ALT + SPACE` and `SUPER + CTRL + SPACE`, so no Space chord is free. On this host `SUPER + E`, `SUPER + D` and `SUPER + U` are free; `SUPER + PERIOD` is free but the Omarchy bindings template suggests it for emojis. `bin/omafind bindings check` reads `hyprctl binds -j` and reports free, ours, or conflict, as omaone does. When the default is taken, setup offers the first free key from `SUPER + E`, `SUPER + D`, `SUPER + U`.
- An optional "Find files" row in `~/.config/omarchy/extensions/omarchy-menu.jsonc`, added only when the user asks for it in setup.

### 7.4 Facts, not prose

omafind computes every status it shows, so the overlay shows the computed values and never an interpretation of them. Any line that explains a result, a scan or a skip is a row of key/value fact tokens (`.fx` on the canvas): a dim key, a value, and nothing else. A sentence is kept only for an instruction, an error with its fix, or a title.

| Where | Keys, in order |
|---|---|
| why line of a result | `leg` (`meaning`, `words`, `meaning + words`), `part` (`image`, `ocr`, `frame`, `speech`, `audio`, `text`, `code`), `at`, `hits`, `z` (fused score) |
| discovery and picker rows | `dirs`, `files`, extension counts (`.png 388`), `rule`, `git`, `kept` (`793/899`) |
| left-out entries | the rule's evidence, as in 4.1 step 6 |
| progress and totals | `selected`, `index`, `time`, `device`, `vram`, `skipped`, `failed`, `queued` |

### 7.3 Jump map

| Kind | Opener |
|---|---|
| pdf | the default web browser, through `omarchy-launch-browser file://…#page=N`, which resolves `xdg-settings get default-web-browser`. Without that helper, `xdg-open` on the file, without a page |
| video, audio | `mpv --start=<seconds>` |
| image | `xdg-open` |
| text, code | `omarchy-launch-editor`, which runs the Omarchy default editor (a terminal editor through `omarchy-launch-tui`). The line argument follows that editor: `+N` for nvim, vim, nano and micro, `path:N` for helix, none for others. Code jumps to `open_line`, found with `rg -n -m1` and a definition pattern, else `loc` |

## 8. Security, privacy, operations

- The global secrets filter (4.3) runs at every entry point to the index.
- `~/.local/share/omafind` is 0700. DBs, model files and the journal are 0600. The socket dir is 0700 and the socket 0600, with an `SO_PEERCRED` UID check.
- The daemon never logs file text or query text.
- No telemetry. No network access except the model download and the runtime build, both started by the user.
- The README states the threat model plainly: the index, snippets, OCR text and thumbnails are stored unencrypted inside the user's home, protected by the host's LUKS disk encryption. External-drive indexes live on the internal disk.
- `bin/omafind status [--json]` reports unit state, socket answer, runtime and model presence with digest check, volumes with file counts and online state, queue length, and permission problems. Exit codes follow omaone: 0 healthy, 1 unit not installed or enabled, 2 unit enabled but not active, 3 unit active but socket silent.

## 9. Testing and phases

### 9.1 Tests

Offline, in milliseconds, following omaone's rules: behavior at module boundaries, one test per behavior, injected clock, no snapshot tests.

- `FakeEmbedder` with deterministic vectors drives fusion, ranking and grouping tests.
- Extractors run against tiny fixture files of every kind.
- Watcher and volume tests use tmpdirs and canned `findmnt --poll` and `lsblk -J` output. Extractor tests run the real tools on fixtures generated at test time with `magick` and `ffmpeg -f lavfi`.
- Discovery candidate selection runs on synthetic trees with known answers.
- A fixture tree of secrets must never produce a `files` row.
- `lib/*.js` runs under `node --test` (`tests/js/*.test.mjs`). QML is checked with `scripts/qmllint.sh`.
- One suite marked manual needs the real model: the parity gate and the eval run.
- CI on ubuntu-latest, actions pinned by SHA: ruff, pytest, node, qmllint. CI installs `fd-find` (linked to `fd`), `ripgrep`, `poppler-utils`, `imagemagick`, `ffmpeg` and `tesseract-ocr`. Docs-only changes skip CI.

### 9.2 Evals

`evals/` starts from DigUp's `evals/*.json` and grows to at least 100 queries over the user's own files, each with the expected file. The headline metric is first-hit rate.

### 9.3 Phases and gates

| Phase | Output | Gate |
|---|---|---|
| 0. Spike (throwaway code) | b11461 Vulkan build; parity, audio and token-budget probes; per-kind rates | text-to-image query ranks the right photo first on a 20-query set. Kill criterion: images miss parity and no fix is in sight |
| 1. Engine and CLI | store, rules, extractors, embedder, fusion, `search --json`, eval harness | first-hit ≥ 90% on the eval set; < 150 ms end to end with a warm server; secrets fixture never indexed |
| 2. Daemon | socket, queue, journal, watcher, volumes, discovery, GPU policy | a new file in a root is searchable in < 5 s; `kill -9` recovers without a full re-crawl; idle RSS < 60 MB |
| 3. Plugin | Service, Overlay, setup view, bindings, menu row | overlay opens in < 100 ms with the shell warm; jump works for every kind; `omarchy plugin validate` clean; installs from a clean clone |
| 4. Hardening | permission checks in `status`, model re-verification on start, README, ADRs 1 to 4 | security checklist in section 8 passes |

### 9.4 ADRs

1. One embedding model. No generative model, no ASR, no captioner chain.
2. Brute-force scan over float16 blobs until more than 1M segments.
3. Scope is `$HOME` and mounted volumes. No root daemon, no fanotify.
4. Stock llama-server subprocess instead of a custom libllama shim, unless the spike shows audio or parity needs the shim.
5. Existing command-line tools over custom code and Python decoders (2.5).

## 10. Corrections to the research note

| Research note | This spec |
|---|---|
| Custom C++ `omafind-embed` over libllama | Stock `llama-server`. It accepts media on `/v1/embeddings` since b11240 (PR #29556). |
| Ollama as fallback | Dropped. On Linux its EmbeddingGemma 2 path needs MLX and fails (ollama issue #18825). |
| llama-cpp-python as an option | Dropped. Its bundled llama.cpp predates `gemma-embedding2`. |
| Arch `extra/llama-cpp` might work | It cannot. 0.6.0 predates b11452. |
| CUDA build | Vulkan build. No CUDA toolkit on the host, and the corpus is small. |
| Fusion uses a per-modality z-score | Per-modality means, then one global deviation (floor 0.02), plus lookup weights. |
| Corpus of ~90k images, first crawl takes hours | The plocate counts were whole-disk. The XDG dirs hold about 1.2k content files today. External drives are unmeasured. |
| One `index.sqlite` | One DB per volume, so drives stay searchable when unplugged. |
| `kinds: ["service","bar-widget","panel"]` | `["service","overlay"]`. |
| Code index opt-in in v1 | Kept: opt-in per repository in setup, `code:` prefix only. |
| Index plaintext is an open risk | Covered by LUKS on this host and stated in the README. |
| Parallel `os.scandir` walk, `git check-ignore`, pypdf, pillow, python-docx, odfpy | `fd`, poppler and `magick` subprocesses (2.5, ADR-5). |
