# Developing omafind

Notes for working on the plugin. Users start at the [README](../README.md).

- [Dev checkout](#dev-checkout)
- [Checks](#checks)
- [Layout](#layout)
- [Runtime build](#runtime-build)
- [CLI reference](#cli-reference)
- [Logs and build errors](#logs-and-build-errors)
- [Content indexing](#content-indexing)
- [Evals](#evals)
- [Threat model](#threat-model)
- [License and reference inputs](#license-and-reference-inputs)

Settings keys are listed in [settings.md](settings.md), the socket messages in [ipc.md](ipc.md), and the UI rules in [DESIGN.md](DESIGN.md).

## Dev checkout

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

Setup creates `~/.local/share/omafind/venv`, copies the user unit into `~/.config/systemd/user/omafind.service`, enables it and waits for `hello`. Repeat setup to apply unit changes. Runtime building and model downloads start through `build-runtime` or the Install button in the setup view. The daemon owns setup jobs, so closing the overlay leaves them running. Pause stops a job and Resume continues it.

When the plugin code changes (a `git pull` in a dev checkout or a marketplace update), the plugin compares `bin/omafind fingerprint` with the `build` the daemon reports and reruns `bin/omafind setup` once. That syncs the venv and restarts the unit. A daemon that starts on a venv missing a dependency logs `omafindd cannot import <module>. Run bin/omafind setup.` to the unit journal and to `~/.local/share/omafind/cache/logs/omafindd-start.log`, then exits 1. A socket bind failure is logged the same way.

Settings live inline on the `radimsem.omafind` entry in `~/.config/omarchy/shell.json`. The plugin writes them through `updateEntryInline`, and the daemon only reads them.

## Checks

```bash
uv sync --project helper --frozen
uv run --project helper ruff check helper tests bin/omafind scripts
uv run --project helper pytest
node --test "tests/js/*.test.mjs"
scripts/qmllint.sh
```

Tests use fakes. The runtime parity test carries the `manual` marker and is excluded by default. It needs the built runtime, the model files and ImageMagick (`magick`), which pre-resizes images to their token budget. Run it and the probe inside a memory cap with no swap (see [AGENTS.md](../AGENTS.md)):

```bash
cap="systemd-run --user --scope --quiet --collect -p MemoryMax=8G -p MemorySwapMax=0 --"
$cap uv run --project helper pytest -m manual tests/helper/test_parity.py
$cap uv run --project helper python scripts/probe.py --stage parity,audio,budget,rates
```

`omarchy plugin validate .` rejects any symlink in the plugin folder, and uv puts one at `helper/.venv/bin/python`. Validate a clean clone, or remove `helper/.venv` first. The installed daemon uses `~/.local/share/omafind/venv` instead.

## Layout

| Path | Holds |
|---|---|
| `ui/` | QML entry views (`Service.qml`, `Overlay.qml`) and their components |
| `lib/` | `.pragma library` JS, tested with `node --test` |
| `helper/omafindd/` | The Python daemon |
| `bin/omafind` | The CLI |
| `scripts/` | Runtime build, probe and `qmllint.sh` |
| `docs/` | [spec.md](spec.md), [ipc.md](ipc.md), [DESIGN.md](DESIGN.md), `adr/` and `research/` |

## Runtime build

The Vulkan build needs `vulkan-headers` and `shaderc`. Prefer installing the remaining build tools with `sudo pacman -S cmake ninja spirv-headers`. The script can bootstrap private copies when those are missing. It runs in a memory-capped systemd user scope (12 GiB, no swap) when the user manager is available. It builds the pinned llama.cpp runtime, then downloads and verifies both pinned model files.

## CLI reference

Run `bin/omafind status` for fact lines or `bin/omafind status --json` for JSON. Status reports runtime and per-file model presence, the last model verification, volumes, queue length and permission problems. The daemon verifies pinned model sizes and digests on startup. These reports do not change the unit and socket exit codes.

| Exit | Meaning |
|---|---|
| 0 | Unit enabled and active, socket answers `hello` |
| 1 | A tool is missing (while the runtime is missing, build packages count too; stderr prints the `pacman` line), or the unit is not installed or not enabled |
| 2 | Unit enabled but not active |
| 3 | Unit active but socket silent |
| 4 | Daemon answers, but the venv is `missing`, `stale` or `unknown` |

`status --json` returns these fields. It reads indexes without opening them for writes.

| Field | Value |
|---|---|
| `unit` | `{enabled, active}` |
| `socket` | `{path, answers}` |
| `tools` | `{missing: [package]}`: missing runtime tools, plus the build packages while the runtime binary is missing |
| `venv` | `{path, state}`; `state` is `ready`, `stale` (does not match `helper/uv.lock`, from `uv sync --check`), `missing` or `unknown` (uv not found or the venv unreadable) |
| `runtime` | `{path, present}` |
| `model` | `{path, files, verified}`; `files` maps pinned filenames to presence booleans; `verified` is the last daemon verdict, false before a report exists |
| `volumes` | `[{uuid, label, files, online}]`; `files` counts rows with `indexed_at` |
| `queue` | Total pending and partial file rows across volume indexes |
| `permissions` | `[{path, expected, actual}]`, with modes such as `0700` and `0644` |
| `recovery` | Last startup `{clean, mode, journal_retried}`, or `{}` before a report exists |
| `problems` | Integrity rebuilds as `[{volume, problem, action, moved_to, at}]`, or `[]` |

Text status prints `venv ready|stale|missing|unknown` (any state but `ready` also prints `next bin/omafind setup` on stderr, whatever the exit code), `permission <path> <actual> want <expected>`, `volume <label> <files> online|offline`, `queue <n>`, `recovery reconcile|none` and `problem <uuid> integrity rebuilt` when applicable. Unreadable or corrupt indexes keep a volume entry with zero counts until recovery rebuilds them. See [ipc.md](ipc.md) for the handshake.

Other commands:

| Command | Does |
|---|---|
| `bin/omafind setup [--json]` | Installs the venv and the user unit, then waits for `hello` |
| `bin/omafind build-runtime` | Builds the runtime and downloads the model |
| `bin/omafind fingerprint` | Prints the plugin build the daemon is compared against |
| `bin/omafind search [--json] [--limit N] QUERY` | Searches from the terminal |
| `bin/omafind reindex [--root PATH]... [--volume UUID] [--incremental]` | Indexes folders |
| `bin/omafind discover --json [--volume UUID]` | Lists the first level of the Folders step |
| `bin/omafind bindings ...` | Manages the shortcut and the menu row |

## Logs and build errors

Setup and search show every failure as a card: what happened, why, and what to do next. A card with a log offers Open log. [ipc.md](ipc.md#errors) lists every code. The logs live under `~/.local/share/omafind`:

| Log | Holds |
|---|---|
| `cache/logs/build-runtime.log` | Full output of the last runtime build (CMake, ninja and the compiler), replaced at each build |
| `cache/logs/llama-server.log` | Output of the embedding server since its last start, replaced at each start. The API key reaches the server only through its environment, so it never appears here. |
| `cache/logs/omafindd-start.log` | A fatal daemon startup error, such as a failed import or socket bind |
| `index/reindex.log` | Output of the last indexing run the daemon started, replaced at each run |

`build-missing-packages` means the runtime build needs an Arch package that is not installed. `build-runtime` and the Install button check for `vulkan-headers` (`/usr/include/vulkan/vulkan_core.h`), `shaderc` (`glslc`), `gcc` (`c++`), `git` and `uv` before the build starts. `setup` only names the missing ones, because it also runs when the daemon updates. `status` lists them under `tools` and exits 1. A build that still stops on a missing `vulkan/`, `spirv/` or `shaderc/` header reports the same code with that header's package. The card names the packages. Install packages runs `omarchy-pkg-add` in a floating terminal and retries the build once they are present. To install every package the check looks for from a terminal:

```bash
sudo pacman -S --needed vulkan-headers shaderc gcc git uv
```

Then press Retry or run `bin/omafind build-runtime`. Any other build error is `build-failed`, with the first error line as the cause. `build-runtime.log` has the full output.

## Content indexing

Required tools: fd 10+, rg, magick, pdfinfo, pdftotext, pdftoppm, git, findmnt, ffmpeg, ffprobe and tesseract. `omafind setup` checks them before installing the daemon. Missing tools produce one `sudo pacman -S --needed ...` command. Missing build packages do not stop setup: while the runtime is missing, setup names them on stderr. With `--json`, setup prints `{"ok":true,"build_missing":[...]}` or `{"ok":false,"error":{...}}` as its last stdout line instead (see [Errors](ipc.md#errors)).

### Reindex, search and discover

```bash
systemd-run --user --scope --quiet --collect -p MemoryMax=8G -p MemorySwapMax=0 -- bin/omafind reindex --root "$HOME/Documents"
bin/omafind search --json --limit 40 "invoice 4412"
```

`bin/omafind discover --json [--volume UUID]` prints the first level of the Folders step (roots and folders) as JSON. It exits 0 with JSON, 1 with one error line on stderr, or 2 without `--json`. The optional volume UUID lists only that mounted non-system volume. The overlay requests children on expansion and receives streamed file counts. Git worktrees are left out: they are unchecked and tagged "worktree", because the main repository already covers their files.

`reindex --incremental` keeps unchanged files and their vectors. The setup view starts this command after saving selected folders, and progress remains available while you search. The daemon writes its child log to `index/reindex.log`.

Without `--root`, reindex reads the plugin's `roots` setting. With no configured roots it exits 2. `--volume UUID` limits reindexing to selected roots on that volume. A `--root` matching a configured root keeps that root's excludes and volume.

Search accepts `img:`, `pdf:`, `vid:`, `aud:` and `doc:`. Text, PDFs, images, video frames and audio windows are indexed. Results are a flat list in score order, with page, source-line or second locations and a `weak` flag. Missing models degrade to keyword results. CLI search exits 0 for a reply (even empty), 1 for no index or a service error, 2 for invalid arguments, and 3 for a silent socket.

### Bindings

```bash
bin/omafind bindings check [--chord "SUPER + E"]
bin/omafind bindings write [--chord "SUPER + E"]
bin/omafind bindings remove
bin/omafind bindings menu add
bin/omafind bindings menu remove
```

`check` reports whether the shortcut is free, bound by omafind or taken, and by what. `check` and `write` use the `shortcut` setting when `--chord` is omitted. `write` and `remove` manage only omafind's marked block in `$XDG_CONFIG_HOME/hypr/bindings.lua` and reload Hyprland when it changes. The menu commands manage a marked Find files row in `$XDG_CONFIG_HOME/omarchy/extensions/omarchy-menu.jsonc`.

### Images, video and audio

Images use `imageBudget`. Screenshots use 280 tokens and video frames use 70. Screenshot names (Screenshot, Screen Shot, CleanShot or SCR-, case-insensitive) and common screen dimensions enable OCR. OCR reads English only (`-l eng`), since only `eng` and `osd` traineddata ship by default, so non-English screenshot text reads badly. OCR text is searchable without a vector. JPEG thumbnails live in `thumbs/<uuid>/`. Video and audio results open through `mpv --start=<seconds>`.

Audio uses 30 s windows with a 25 s hop, skips RMS at or below 0.003, and keeps tails with at least 2 s of new audio. `audio:false` skips audio files with code `audio-off` and indexes videos as frames only. Silent files are skipped. Video frames are extracted and committed in passes of at most 16 frames before the soundtrack starts. Long audio is extracted and committed in batches of at most 16 windows, which keeps decoded payload memory bounded, and PCM streams one window at a time. A failed soundtrack leaves successfully embedded frames in a `partial` video. Size caps are 8 GiB for video, 2 GiB for audio, 512 MiB for PDF and 16 MiB otherwise.

### Index storage

Indexes live in `$XDG_DATA_HOME/omafind/index/<uuid>.sqlite` (default `~/.local/share/omafind/index`), mode 0600. Paths are relative to each filesystem's mount point (the home mount for its UUID, otherwise the shortest target). A CLI reindex holds `index.lock`. Completed PDF windows commit atomically, and the journal retries interrupted batches. The daemon reloads changed indexes before searching.

During reindex the daemon serves words-only results with a `degraded` error of code `index-running` and rejects `warm` with the same error. A reindex that finds the daemon's server warm prints `waiting index.lock`, and the daemon stops that server within half a second. Incremental reindexes the daemon starts itself, after a file change or a drive returns, reuse the daemon's server, so search keeps its meaning results while they run.

### Rules

The shared fd rules exclude hidden files, ignored paths, heavy directories and DigUp's secret-name patterns, including encrypted key stores. Media folders with at least 300 files of one kind and 70% machine names are visible dataset proposals. Checked folders are indexed, including datasets. Text is capped at 16 MiB and PDFs at 512 MiB. An Office file's XML is streamed, not unpacked: extraction stops after 64 MiB of XML, at a single tag over 2 MiB or at the 16 MiB text cap counted in characters, and fails past 256 levels of nesting, so a small file that decompresses to gigabytes stays small in memory. HTML and Office line numbers describe extracted text, so their openers omit the line argument.

## Evals

Offline fixture evals use FakeEmbedder and never start a model:

```bash
uv run --project helper python evals/run.py --queries evals/fixture.json
```

`--index <sqlite-file-or-index-directory>` uses the installed embedding model for manual evals with DigUp's `{base, queries:[{q, expect, tag}]}` shape. Repeat `--queries` to score several sets as one, and `--gate` sets the minimum first-hit fraction (default 0.9).

`evals/personal.json` and `evals/media.json` are personal and gitignored, because they name your own files. To make one, write a file in the same shape:

```json
{
  "base": "~/Documents",
  "queries": [
    {"q": "invoice 4412", "expect": ["invoices/2025-03.pdf"], "tag": "pdf"}
  ]
}
```

`base` is the folder your `expect` paths are relative to. Then run it against your installed index:

```bash
systemd-run --user --scope --quiet --collect -p MemoryMax=8G -p MemorySwapMax=0 -- uv run --project helper python evals/run.py --index ~/.local/share/omafind/index --queries evals/personal.json
```

CI provides a `magick` wrapper around `convert` and `identify` when Ubuntu supplies ImageMagick 6. Product code always invokes `magick`.

## Threat model

The index, snippets, OCR text and thumbnails are stored unencrypted inside the user's home. The host's LUKS disk encryption protects them while the disk is locked. External-drive indexes and cached thumbnails live on the internal disk, so they stay after a drive is unplugged. A process running as the same user can read this data, and omafind adds no encryption while the user is logged in.

The data directory and its child directories use 0700. Databases, model files and the journal use 0600. The socket directory uses 0700 and the socket uses 0600. The daemon checks the connecting UID with `SO_PEERCRED`. The shared secrets filter runs at every indexing entry point. It excludes known secret names, but cannot identify every sensitive document.

The daemon never logs file text or query text. It sends no telemetry. Network access is limited to user-started runtime builds and model downloads, plus the local embedding server on loopback.

The daemon runs as the user and searches selected folders in `$HOME` and mounted volumes. It needs no root daemon or fanotify. Status reports permission problems without changing permissions or its exit code.

## License and reference inputs

omafind is [MIT licensed](../LICENSE), copyright 2026 radimsem.

The reference inputs `photo.jpg`, `screen.png` and `speech.wav` in `tests/fixtures/reference` come from [DigUp](https://github.com/ARahim3/DigUp), copyright 2026 Abdur Rahim, under the [MIT license](https://github.com/ARahim3/DigUp/blob/main/LICENSE).
