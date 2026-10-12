# ADR-5: Existing command-line tools over custom code and Python decoders

Status: accepted, 2026-10-12, before issue #2 starts.

## Context

The spec planned a Python file walk (parallel `os.scandir`), batched `git check-ignore`, a `*.noindex` marker, polling of `/proc/self/mountinfo`, and Python decoders for PDFs, images and Office files (`pypdf`, `pypdfium2`, Pillow, `python-docx`, `odfpy`). Omarchy already installs tools that do each of these jobs, and the rest of the stack already shells out to `ffmpeg`, `tesseract` and `magick`.

Measured on this host (`$HOME` holds 3.9 M files):

| Walk | Time | Files |
|---|---|---|
| serial `os.scandir`, every file | 48.2 s | 3,964,291 |
| `fd -t f -H --no-ignore`, every file, warm cache | 1.6 s | 3,926,145 |
| `fd -t f -e md -e txt -e pdf -e docx -e odt -e html`, default rules | 0.16 s | 18,397 |
| `plocate -c "$HOME/"` | 17.2 s | 4,342,655 |

`fd` already skips dot files, honors `.gitignore` in the parent repository and `.ignore` files, and takes `-E` globs. A check on fixtures confirmed `.ignore` with `*` leaves a folder out and `-E` globs remove `id_rsa*`, `credential*` and `*.pem`. It also showed one trap: `fd` started inside a directory that a parent `.gitignore` excludes still lists that directory's files.

## Decision

omafind drives the tools in spec 2.5 as subprocesses. Each is required, and each job has one code path, with no Python fallback.

- **Walk and rules.** `fd` with the skip rules as arguments is the one predicate for discovery, crawl and watcher. The watcher re-lists the root with `--full-path` filters, never from inside the changed directory. Python keeps the dataset rule and size caps. `.ignore` replaces `*.noindex`. `git check-ignore` is gone.
- **Mounts.** `findmnt --poll` for events, `lsblk -J` for drive facts.
- **PDF.** `pdfinfo`, `pdftotext`, `pdftoppm`.
- **Images, frames, rendered pages.** `magick`. Every image goes through the `-filter Catrom` pre-resize that passed parity in ADR-4. Pillow's `BICUBIC`, which issue #3 proposed as DigUp's reference, was never measured against the bf16 reference.
- **docx and odt.** stdlib `zipfile` and XML parsing. pandoc is not installed, and `soffice --headless` costs a second or more per file.
- **Video and audio.** `ffmpeg` and `ffprobe` decode and scale. Python keeps DigUp's 8 × 8 average hash and RMS gate, since `mpdecimate` and `silencedetect` would change the tested frame and window positions.
- **Code words leg.** `rg` over `codeRoots` per query. `code.sqlite` keeps stretches and vectors only.
- **Opener.** `omarchy-launch-editor` replaces the `editor` setting.
- **Not used.** plocate: its database is up to a day old, prunes `/media` and `/mnt`, and a path-prefix count takes 17 s.

The helper's Python dependencies stay `httpx`, `numpy` and `watchdog`. SQLite FTS5, the numpy vector scan and the fusion math stay as specified.

## Consequences

- `bin/omafind setup` and `status --json` gain a `tools` check that prints one `sudo pacman -S --needed` line. `poppler` is the only package Omarchy does not install directly.
- CI installs `fd-find` (linked to `fd`), `ripgrep`, `poppler-utils`, `imagemagick`, `ffmpeg` and `tesseract-ocr`. Extractor tests run the real tools on fixtures generated at test time.
- Tool output formats become contracts. Each issue's first step proves the flags it relies on, on this host.
- A file walk cannot be resumed mid-way, and does not need to be: a rerun costs under 2 s.
- Revisit if omafind targets hosts without Omarchy's package set.
