# omafind

omafind is an Omarchy 4 plugin for local content search across text, PDFs, images, video, audio and opt-in code repositories. It uses an overlay and a Python daemon, `omafindd`, with a local embedding runtime. This scaffold provides the daemon handshake and runtime setup; indexing and search arrive in later issues.

## Develop

Requires Omarchy 4, Quickshell and `uv` with Python 3.12 or newer.

```bash
git clone git@github.com:radimsem/omafind.git
cd omafind
mkdir -p ~/.config/omarchy/plugins
ln -s "$PWD" ~/.config/omarchy/plugins/radimsem.omafind
omarchy-shell shell rescanPlugins
omarchy plugin enable radimsem.omafind
bin/omafind setup
bin/omafind build-runtime
```

Setup creates `~/.local/share/omafind/venv`, copies the user unit into `~/.config/systemd/user/omafind.service`, enables it and waits for `hello`. Repeat setup to apply unit changes. Runtime building and model downloads start through `build-runtime` or the setup view’s Download button. The daemon owns setup jobs, so closing the overlay leaves them running; Pause stops a job and Resume continues it.

The Vulkan build needs `vulkan-headers` and `shaderc`. Prefer installing the remaining build tools with `sudo pacman -S cmake ninja spirv-headers`. The script can bootstrap private copies when those are missing. It runs in a memory-capped systemd user scope (12 GiB, no swap) when the user manager is available. It builds the pinned llama.cpp runtime, then downloads and verifies both pinned model files.

Run `bin/omafind status` for fact lines or `bin/omafind status --json` for JSON. Status reports runtime and per-file model presence, the last model verification, volumes, queue length and permission problems. The daemon verifies pinned model sizes and digests on startup. These reports do not change the unit and socket exit codes.

| Exit | Meaning |
|---|---|
| 0 | Unit enabled and active, socket answers `hello` |
| 1 | Unit not installed or not enabled |
| 2 | Unit enabled but not active |
| 3 | Unit active but socket silent |

`status --json` returns these fields. It reads indexes without opening them for writes.

| Field | Value |
|---|---|
| `unit` | `{enabled, active}` |
| `socket` | `{path, answers}` |
| `tools` | `{missing: [tool]}` |
| `runtime` | `{path, present}` |
| `model` | `{path, files, verified}`; `files` maps pinned filenames to presence booleans; `verified` is the last daemon verdict, false before a report exists |
| `volumes` | `[{uuid, label, files, online}]`; `files` counts rows with `indexed_at`, excluding `code.sqlite` |
| `queue` | Total pending and partial file rows across volume indexes |
| `permissions` | `[{path, expected, actual}]`, with modes such as `0700` and `0644` |
| `recovery` | Last startup `{clean, mode, journal_retried}`, or `{}` before a report exists |
| `problems` | Integrity rebuilds as `[{volume, problem, action, moved_to, at}]`, or `[]` |

Text status prints `permission <path> <actual> want <expected>`,
`volume <label> <files> online|offline`, `queue <n>`, `recovery reconcile|none`
and `problem <uuid> integrity rebuilt` when applicable.
Unreadable or corrupt indexes retain a volume entry with zero counts until recovery rebuilds them.
See [docs/ipc.md](docs/ipc.md) for the handshake.

Settings live inline on the `radimsem.omafind` entry in `~/.config/omarchy/shell.json`. The plugin writes them through `updateEntryInline`; the daemon only reads them. Later issues add keys.

| Key | Type | Default |
|---|---|---|
| `setupDone` | bool | `false` |
| `gpu` | `"auto"` or `"never"` | `"auto"` |
| `audio` | bool | `true` |
| `roots` | `[{path, volume, excludes: [path]}]` | `[]` |
| `codeRoots` | list of absolute repository paths | `[]` |
| `ignoredVolumes` | list of filesystem UUIDs the new-drive toast skips | `[]` |
| `imageBudget` | 70, 140 or 280 | `140` |
| `maxResults` | int, clamped to 10..200 | `40` |
| `warmMinutes` | int, clamped to 0..60 | `5` |
| `shortcut` | uppercase `MODS + KEY`; mods: SUPER, SHIFT, CTRL, ALT | `"SUPER + E"` |

## Threat model

The index, snippets, OCR text and thumbnails are stored unencrypted inside the user's home.
The host's LUKS disk encryption protects them while the disk is locked.
External-drive indexes and cached thumbnails live on the internal disk, so they stay after a drive is unplugged.
A process running as the same user can read this data; omafind adds no encryption while the user is logged in.

The data directory and its child directories use 0700. Databases, model files and the journal use 0600.
The socket directory uses 0700 and the socket uses 0600. The daemon checks the connecting UID with `SO_PEERCRED`.
The shared secrets filter runs at every indexing entry point. It excludes known secret names, but cannot identify every sensitive document.
The daemon never logs file text or query text. It sends no telemetry.
Network access is limited to user-started runtime builds and model downloads, plus the local embedding server on loopback.

The daemon runs as the user and searches selected folders in `$HOME` and mounted volumes.
It needs no root daemon or fanotify. Status reports permission problems without changing permissions or its exit code.

## Check

```bash
uv sync --project helper --frozen
uv run --project helper ruff check helper tests bin/omafind scripts
uv run --project helper pytest
node --test "tests/js/*.test.mjs"
scripts/qmllint.sh
```

Tests use fakes. The runtime parity test carries the `manual` marker and is excluded by default. It needs the built runtime, the model files and ImageMagick (`magick`), which pre-resizes images to their token budget. Run it and the probe inside a memory cap with no swap (see AGENTS.md):

```bash
cap="systemd-run --user --scope --quiet --collect -p MemoryMax=8G -p MemorySwapMax=0 --"
$cap uv run --project helper pytest -m manual tests/helper/test_parity.py
$cap uv run --project helper python scripts/probe.py --stage parity,audio,budget,rates
```

`omarchy plugin validate .` rejects any symlink in the plugin folder, and uv puts one at `helper/.venv/bin/python`. Validate a clean clone, or remove `helper/.venv` first. The installed daemon uses `~/.local/share/omafind/venv` instead.

## License and reference inputs

omafind is [MIT licensed](LICENSE), copyright 2026 radimsem.

The reference inputs `photo.jpg`, `screen.png` and `speech.wav` in `tests/fixtures/reference` come from [DigUp](https://github.com/ARahim3/DigUp), copyright 2026 Abdur Rahim, under the [MIT license](https://github.com/ARahim3/DigUp/blob/main/LICENSE).

## Content indexing

Required tools: fd 10+, rg, magick, pdfinfo, pdftotext, pdftoppm, git, findmnt,
ffmpeg, ffprobe and tesseract.
`omafind setup` checks them before installing the daemon. Missing tools produce
one `sudo pacman -S --needed ...` command.

```bash
systemd-run --user --scope --quiet --collect -p MemoryMax=8G -p MemorySwapMax=0 -- bin/omafind reindex --root "$HOME/Documents"
bin/omafind search --json --limit 40 "invoice 4412"
```

`bin/omafind discover --json [--volume UUID]` prints the name-only setup scan.
It exits 0 with JSON, 1 with one error line on stderr, or 2 without `--json`.
The optional volume UUID scans only that mounted non-system volume.

`reindex --incremental` keeps unchanged files and their vectors. The setup view
starts this command after saving selected folders; progress remains available
while you search. The daemon writes its child log to `index/reindex.log`.

Without `--root`, reindex reads the plugin's `roots` setting. With no configured
roots it exits 2. `--volume UUID` limits reindexing to selected roots on that volume.
A `--root` matching a configured root keeps that root's excludes and volume.
Search accepts `img:`, `pdf:`, `vid:`, `aud:`, `doc:` and `code:`. Text, PDFs, images,
video frames and audio windows are indexed. `codeRoots` selects git repositories
indexed through `git ls-files`, searched only by `code:` queries, with `rg` reading
the files live.
Results are a flat list in score order, with page, source-line or second locations
and a `weak` flag. Missing
models degrade to keyword results. CLI search exits 0 for a reply (even empty),
1 for no index or a service error, 2 for invalid arguments, and 3 for a silent socket.

Manage the overlay shortcut and optional menu row with:

```bash
bin/omafind bindings check [--chord "SUPER + E"]
bin/omafind bindings write [--chord "SUPER + E"]
bin/omafind bindings remove
bin/omafind bindings menu add
bin/omafind bindings menu remove
```

`check` reports conflicts and suggests a free shortcut. `check` and `write`
use the `shortcut` setting when `--chord` is omitted. `write` and `remove`
manage only omafind's marked block in `$XDG_CONFIG_HOME/hypr/bindings.lua` and
reload Hyprland when it changes. The menu commands manage a marked Find files
row in `$XDG_CONFIG_HOME/omarchy/extensions/omarchy-menu.jsonc`.

Images use `imageBudget`; screenshots use 280 tokens and video frames use 70.
Screenshot names (Screenshot, Screen Shot, CleanShot or SCR-, case-insensitive)
and common screen dimensions enable OCR. OCR reads English only (`-l eng`), since
only `eng` and `osd` traineddata ship by default, so non-English screenshot text
reads badly.
OCR text is searchable without a vector. JPEG thumbnails live in `thumbs/<uuid>/`.
Video and audio results open through `mpv --start=<seconds>`.

Audio uses 30 s windows with a 25 s hop, skips RMS at or below 0.003, and keeps
tails with at least 2 s of new audio. `audio:false` skips audio files with detail
`audio search is off` and indexes videos as frames only. Silent files are skipped.
Video frames are extracted and committed in passes of at most 16 frames before
the soundtrack starts. Long audio is extracted and committed in batches of at most
16 windows, keeping decoded payload memory bounded as well as streaming PCM one
window at a time.
A failed soundtrack leaves successfully embedded frames in a `partial` video.
Size caps are 8 GiB for video, 2 GiB for audio, 512 MiB for PDF and 16 MiB otherwise.

Indexes live in `$XDG_DATA_HOME/omafind/index/<uuid>.sqlite` (default
`~/.local/share/omafind/index`), mode 0600. Paths are relative to each filesystem's
mount point (the home mount for its UUID, otherwise the shortest target).
A CLI reindex holds `index.lock`; completed PDF windows commit atomically,
and the journal retries interrupted batches. The daemon reloads changed indexes
before searching. During reindex it serves words-only results with
`degraded:"indexing in progress"` and rejects `warm` with the same reason.
A reindex that finds the daemon's server warm prints `waiting index.lock`; the daemon
stops that server within half a second.
Incremental reindexes the daemon starts itself, after a file change or a drive
returns, reuse the daemon's server, so search keeps its meaning results while
they run.

The shared fd rules exclude hidden files, ignored paths, heavy directories and
DigUp's secret-name patterns, including encrypted key stores. Machine-named
folders with at least 300 same-kind files and 70% machine names are excluded unless
selected as roots. Text is capped at 16 MiB and PDFs at 512 MiB. HTML and Office
line numbers describe extracted text; their openers omit the line argument.

Offline fixture evals use FakeEmbedder and never start a model:

```bash
uv run --project helper python evals/run.py --queries evals/fixture.json
```

`--index <sqlite-file-or-index-directory>` uses the installed embedding model
for manual evals with DigUp's `{base, queries:[{q, expect, tag}]}` shape. The owner
maintains `evals/personal.json` over their own files.
CI provides a `magick` wrapper around `convert`/`identify` when Ubuntu supplies
ImageMagick 6. Product code always invokes `magick`.
