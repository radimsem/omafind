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
