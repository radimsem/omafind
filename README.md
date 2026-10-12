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

Setup creates `~/.local/share/omafind/venv`, copies the user unit into `~/.config/systemd/user/omafind.service`, enables it and waits for `hello`. Repeat setup to apply unit changes. Runtime building and model downloads happen only through `build-runtime`.

The Vulkan build needs `vulkan-headers` and `shaderc`. Prefer installing the remaining build tools with `sudo pacman -S cmake ninja spirv-headers`. The script can bootstrap private copies when those are missing. It runs in a memory-capped systemd user scope (12 GiB, no swap) when the user manager is available. It builds the pinned llama.cpp runtime, then downloads and verifies both pinned model files.

Run `bin/omafind status` for fact lines or `bin/omafind status --json` for JSON. Status reports runtime and per-file model presence. `build-runtime` verifies model digests. Runtime and model presence do not change the unit and socket exit codes.

| Exit | Meaning |
|---|---|
| 0 | Unit enabled and active, socket answers `hello` |
| 1 | Unit not installed or not enabled |
| 2 | Unit enabled but not active |
| 3 | Unit active but socket silent |

JSON keys are `unit: {enabled, active}`, `socket: {path, answers}`, `runtime: {path, present}` and `model: {path, files}`. `files` maps each pinned filename to a presence boolean. See [docs/ipc.md](docs/ipc.md) for the handshake.

Settings live inline on the `radimsem.omafind` entry in `~/.config/omarchy/shell.json`. The plugin writes them through `updateEntryInline`; the daemon only reads them. Later issues add keys.

| Key | Type | Default |
|---|---|---|
| `setupDone` | bool | `false` |
| `gpu` | `"auto"` or `"never"` | `"auto"` |
| `audio` | bool | `true` |
| `roots` | `[{path, volume, excludes: [path]}]` | `[]` |
| `maxResults` | int, clamped to 10..200 | `40` |
| `warmMinutes` | int, clamped to 0..60 | `5` |

Index data, snippets, OCR text and thumbnails are stored unencrypted inside the user's home. On the target host, LUKS protects them while the disk is locked. External-drive indexes live on the internal disk. omafind sends no telemetry; network access is limited to user-started runtime builds and model downloads.

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

## Text and PDF indexing

Required tools: fd 10+, rg, magick, pdfinfo, pdftotext, pdftoppm, git and findmnt.
`omafind setup` checks them before installing the daemon. Missing tools produce
one `sudo pacman -S --needed ...` command.

```bash
systemd-run --user --scope --quiet --collect -p MemoryMax=8G -p MemorySwapMax=0 -- bin/omafind reindex --root "$HOME/Documents"
bin/omafind search --json --limit 40 "invoice 4412"
```

Without `--root`, reindex reads the plugin's `roots` setting. With no configured
roots it exits 2. `--volume UUID` limits reindexing to selected roots on that volume.
A `--root` matching a configured root keeps that root's excludes and volume.
Search accepts `img:`, `pdf:`, `vid:`, `aud:`, `doc:` and `code:`. Only text and PDFs
are indexed so far, so the other prefixes return no hits. Results are a flat list
in score order, with page or source-line locations and a `weak` flag. Missing
models degrade to keyword results. CLI search exits 0 for a reply (even empty),
1 for no index or a service error, 2 for invalid arguments, and 3 for a silent socket.

Indexes live in `$XDG_DATA_HOME/omafind/index/<uuid>.sqlite` (default
`~/.local/share/omafind/index`), mode 0600. Paths are relative to each filesystem's
mount point (the home mount for its UUID, otherwise the shortest target).
A CLI reindex holds `index.lock`; completed PDF windows commit atomically,
and the journal retries interrupted batches. The daemon reloads changed indexes
before searching. During reindex it serves words-only results with
`degraded:"indexing in progress"` and rejects `warm` with the same reason.
A reindex that finds the daemon's server warm prints `waiting index.lock`; the daemon
stops that server within half a second.

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
