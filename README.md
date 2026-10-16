# omafind

Search your local files by content from an Omarchy overlay.

omafind is an Omarchy 4 plugin. Describe what you remember, or type words from the file, and it finds documents, PDF pages, images, video moments and audio clips on your machine.

![omafind finding images, video moments, PDF pages and audio clips from typed descriptions](docs/media/demo.gif)

- Searches by meaning and by exact words. Words answer first and meaning re-ranks.
- Reads text documents, PDFs, images (screenshots get OCR), video and audio.
- Runs locally on one embedding model, EmbeddingGemma 2, served by `llama-server`.
- Opens a result at the match: the page, the line or the second.

## Requirements

- Omarchy 4.
- About 2 GB of free disk for the install: the engine build takes roughly 800 MB while it runs, and the model files are 865 MB. The index grows with your files. Indexing pauses below 2 GB free.
- A Vulkan GPU makes indexing much faster. Without one, omafind falls back to the CPU.
- Build packages for the engine: `vulkan-headers`, `shaderc`, `gcc`, `git` and `uv`. Setup checks for them and offers to install what is missing.

## Install

```bash
omarchy plugin add https://github.com/radimsem/omafind --enable
```

Open the overlay once:

```bash
omarchy-shell shell toggle radimsem.omafind '{"view":"search"}'
```

It starts in setup until the engine is installed. Setup has three steps:

1. Search engine. Install builds the embedding server (about 3 minutes), then downloads and verifies the model. You can close the window while it runs. Pause stops the job and Resume continues it.
2. Folders. Pick what to search. Your Documents, Pictures, Videos, Music, Downloads and Desktop folders start checked.
3. Index. The first index runs, and you choose the shortcut that opens omafind. Indexing keeps going after you close setup.

## Use

Press the shortcut you chose in setup (SUPER + E by default). Type to search. Start with a prefix to search one kind: `img:`, `pdf:`, `doc:`, `vid:` or `aud:`.

| Key | Action |
|---|---|
| `Up` `Down`, `Ctrl J` `Ctrl K`, `Ctrl N` `Ctrl P` | Move across results |
| `Enter` | Open the result at the match |
| `Ctrl Enter` | Show the result in its folder |
| `Ctrl Space` | Play or pause an audio or video preview |
| `Ctrl C` | Copy the result's path |
| `Ctrl I` | Show indexing progress |
| `Ctrl ,` | Open settings |
| `Esc` | Clear the query, then close |

Settings changes the shortcut, adds or removes the Find files row in the Omarchy menu, and reopens the Folders step. Every setting key is listed in [docs/settings.md](docs/settings.md).

## Update and remove

```bash
omarchy plugin update radimsem.omafind
```

omafind then brings its helper and daemon up to date on its own.

To remove it, run these in order:

```bash
# Take out the shortcut and the Find files menu row
~/.config/omarchy/plugins/radimsem.omafind/bin/omafind bindings remove
~/.config/omarchy/plugins/radimsem.omafind/bin/omafind bindings menu remove

# Stop the daemon and delete its service
systemctl --user disable --now omafind.service
rm ~/.config/systemd/user/omafind.service

# Remove the plugin
omarchy plugin remove radimsem.omafind
```

The index, thumbnails and model stay in `~/.local/share/omafind`. Delete that folder to free the space.

## Troubleshooting

- Run `~/.config/omarchy/plugins/radimsem.omafind/bin/omafind status` to see what is missing. Exit code 0 means the daemon is up. The other codes are in [docs/development.md](docs/development.md#cli-reference).
- Setup shows a card for every failure. A missing package has an Install packages button. From a terminal, run `sudo pacman -S --needed vulkan-headers shaderc gcc git uv`, then press Retry.
- Results say they are keyword matches only: the embedding server is starting or did not start. Open the log from the card, or read `~/.local/share/omafind/cache/logs/llama-server.log`.
- Indexing is paused because less than 2 GB of disk is free. It resumes by itself once you free space.
- Another bind already uses your shortcut: press `Ctrl ,` in the overlay and record a different one.

[docs/development.md](docs/development.md#logs-and-build-errors) lists every log.

## Privacy

Everything stays on your machine. The index, snippets, OCR text and thumbnails are stored unencrypted in your home folder, and omafind sends no telemetry. The network is used only for the engine build and the model download. The [threat model](docs/development.md#threat-model) has the details.

## More

- [docs/settings.md](docs/settings.md): every setting key
- [docs/development.md](docs/development.md): dev checkout, checks, CLI, indexing and evals
- [docs/ipc.md](docs/ipc.md): the socket messages between the overlay and the daemon

omafind is [MIT licensed](LICENSE).
