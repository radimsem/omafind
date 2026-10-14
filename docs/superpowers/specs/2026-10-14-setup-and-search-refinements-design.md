# Setup and search refinements

Date: 2026-10-14. Branch: `fix/setup-and-search-refinements`, one pull request.

The owner smoke-tested the first-run setup and the search overlay on the live host (3440x1440, scale 1) after #12 to #16 landed. This spec fixes what that run found. It has three parts: A reworks the Folders step, B ports the shortcut capture from omaone, C fixes search and rendering. The base spec (`2026-10-11-omafind-design.md`) still holds where this one is silent.

## Goals

- The Folders step paints at once and stays fast on any `$HOME`, because it reads a folder's children only when the user expands it.
- Every folder the user checks is indexed. No default rule removes files the user chose without showing it.
- Text is sharp at scale 1, and image and PDF previews show their content at the size of the preview box.
- Opening a text result lands on the matched line.
- The keyboard covers the result list the way terminal users expect.

## Non-goals

- No change to the settings shape: `roots` with `excludes` and `codeRoots` stay as they are.
- No change to indexing, embedding or ranking.
- No new search features. The Ctrl+Space preview hint is removed, not implemented.

## A. Folders step

### A1. Daemon and IPC

Discovery becomes lazy. It replaces the up-front candidate scan.

`discover_start` replies after one directory read per root. The roots are `$HOME` and the mount point of each mounted volume. The reply lists the folders directly under each root as `{path, name, xdg, repo, hasChildren}`. Hidden folders, the heavy and vendor names in `rules.py` and secrets are left out by the existing rules. The six XDG folders (documents, pictures, videos, music, download, desktop) arrive with `xdg: true`. `repo` is true when the folder holds `.git`.

After the reply, one background thread runs one `fd` pass per root over the indexable kinds. It builds the rolled-up `counts` map that `discovery.scan()` builds today, keyed by folder path, and broadcasts `discover_counts {counts: {path: {text, pdf, image, video, audio, dirs}}, done}` about every 250 ms with the entries that changed. The dot and heavy counting passes, the `fd -I` repo search and the per-repo `git ls-files` at scan time are removed. The walk keeps the current memory cap and stops when the overlay sends `discover_stop` or the connection closes.

`discover_children {path}` returns one level: `{path, dirs: [{path, name, repo, hasChildren, counts, rule}]}`, sorted by indexable files, then by name. Counts come from the map. When the walk has not reached the folder yet, the daemon reads that one directory, returns the children with `counts: null`, and the counts arrive later through `discover_counts`.

`discover_tree`, the `candidates` field of `discover_result` and `discovery._root_tree` are removed. `docs/ipc.md` documents the new and changed messages in the same pull request.

### A2. Leave-out rules

- `generated` and `no-kind` are deleted from `leftout.py`, with their tests.
- `dataset` becomes media only: a folder with 300 or more files of one media kind (image, video or audio), of which at least 70% are machine-named. Text and PDF never count. Camera prefixes (`img`, `dsc`, `dscn`, `pxl`, `mvimg`, `vid`, `gopr`) are not machine names, and neither are ISO-date stems.
- A dataset is a visible proposal. It arrives as `rule: "dataset"` with its evidence (`{kind, files, named}`) on the child row and starts unchecked. `rules.datasets` no longer filters at scan time, and `rules.keep` no longer drops dataset files at index time. A folder the user checks is always indexed.
- Secrets, the size caps, hidden paths and the heavy and vendor names do not change.

### A3. Selection model

`lib/tree.js` keeps two path sets in memory, `chosen` and `skipped`.

- A folder is searched when its nearest ancestor-or-self in either set is in `chosen`.
- `mark(path)` returns `on`, `off` or `mixed`. `mixed` means some choice below the folder differs from its own state, at any depth.
- Clicking a folder sets it and clears every choice below it. Clicking a `mixed` folder selects it whole.
- Children render from `mark` as soon as they load, so the children of a checked folder show checked.
- XDG folders start in `chosen` when the step opens, before their counts arrive, so no checkbox flips under the user. An empty one adds nothing to the index. A dataset proposal starts in `skipped` under a chosen parent.
- On save, `Tree.toRoots` turns the sets into `roots` with `excludes`. Repo folders with the code toggle on go into `codeRoots`. Repos inside a checked folder keep today's behavior: their documents and media are indexed, their code only through the code toggle.

### A4. List and rows

`SetupFolders.qml` replaces its `Column` and `Repeater` of `FolderRow` with one `ListView` over a flat model of the visible rows.

- Expanding a row sends `discover_children` once and caches the reply in `Service`. Collapsing removes the child rows from the model and keeps the cache.
- A row shows, left to right: checkbox, disclosure chevron (absent when `hasChildren` is false), name, a `repo` tag with a code toggle when it applies, then Text, PDF, Images, Video, Audio, Index and Time.
- Top-level rows show `~/name`. Deeper rows show the folder name only, indented by depth.
- Counts not yet known show a dim placeholder glyph per column and one small spinner on the row.
- A dataset row carries a `dataset` tag and its evidence, for example `images 1,418 · named 96%`.
- The left-out ledger (`LeftOutLedger.qml`, `SetupLeaveOut.qml`, hatched rows, "NOT INDEXED") is removed. The user leaves a subfolder out by unchecking it in the tree.
- The section labels and their uppercase notes, and the split into home folders and "found elsewhere", are removed. Volumes are extra top-level rows, unchecked.
- Header facts: `folders <n> · scanning` while the walk runs, then `scanned in <s> s` rounded to one decimal. `volumes 0`, `read names only`, `roots $HOME` and the `dirs` count are removed.
- Footer: `selected <files> files · index <size> · time <t> · device <gpu>`, totalled over searched folders and updated as counts arrive.

## B. Shortcut capture

The Index step's shortcut row ports omaone's capture (`ui/ShortcutRow.qml`, `lib/keycombo.js`, `ui/settings/Shortcuts.qml`).

- The row shows the current chord as keycaps and a Change button. Recording shows "Press a shortcut" with an accent border, and Change becomes Cancel. Esc, focus loss or 30 s without a key cancels.
- While recording, Hyprland is in an `omafind-record` submap so bound keys do not fire. The overlay polls the active submap every second and stops recording if it changed. Finish and cancel restore the default submap.
- `checkCombo` requires Super, or a lone F1 to F35. It checks the captured chord against live binds and treats omafind's own block as free. A new read-only request `binds_get` returns `hyprctl binds -j` as `{binds: [{chord, description}]}`. A conflict shows one sentence: "<Chord> is already bound to <description> in Hyprland. Press another shortcut."
- Save stays as it is: `persist({shortcut})`, then `bin/omafind bindings write` and `hyprctl reload`.
- The hard-coded chord list (`setup.js`, `SetupIndex.qml`, `bindings.py`) and `Setup.nextChord` are removed. This also fixes the step waiting forever on "Checking your bindings" when the saved chord is not one of the three.

## C. Search and rendering

### C1. Sharp text

- A shared `ui/Label.qml` wraps `Text` with `renderType: Text.NativeRendering`. Every static `Text` in the overlay uses it. Text inputs keep their own rendering.
- The minimum size is 11 px. 10 px is allowed only for bold uppercase headers. `Tokens.tiny` is removed.
- Letter spacing is rounded to whole pixels.
- Footer hints drop the opacity on top of `Tokens.dim`.

### C2. Indexing progress popover

- The per-kind rows in `SetupIndex.qml` move into `ui/KindProgress.qml`, which takes `progress`. The Index step and the search view both use it.
- In the search view, a click on the footer progress or Ctrl+I opens it as a popover above the footer. Esc or Ctrl+I closes it.
- A new read-only request `index_progress` returns the latest `progress`, so the popover fills before the next broadcast.
- The footer progress stays visible while a query is typed.

### C3. Keys

- Ctrl+N moves down, Ctrl+P moves up.
- PageDown and PageUp move by one visible page. Ctrl+Home and Ctrl+End select the first and last result.
- Ctrl+C copies the selected query text when the query has a selection, otherwise the result path.

### C4. Previews

- Images: the preview loads the original file with `sourceSize` set to the box size times the device pixel ratio, and `mipmap: true`. The 128 px thumbnail stays for list rows and for offline volumes. Formats Qt cannot decode (HEIC, RAW) get a cached `magick` render at the box size in `preview_dir`.
- PDF pages use the full media area (600x420), render at twice that size and set `mipmap: true`.
- Video frames set `mipmap: true`.

### C5. Open at the matched line

- `ipc.py` keeps the stored jump of every result id that is still present in a later `results` reply with the same seq, instead of dropping all jumps.
- `open` accepts an optional `line`. The overlay sends `preview.jump` when it has one. The daemon prefers the client line, then the stored jump, then the chunk start.
- The open path stays `omarchy-launch-editor +LINE path`.

### C6. Smaller fixes

- The search latency shows whole milliseconds. The scan time shows one decimal.
- The weaker-matches row expands on click and collapses on a second click. Its count goes through `Format.count`.
- The Ctrl+Space hint is removed.
- Step 3's title becomes "Indexing finished" when the run completes and "Indexing stopped" when it fails or is paused.

## Copy

New strings follow the copy rules: sentence case, no em dashes in prose, an error says what happened, why and what next.

- "Press a shortcut"
- "<Chord> is already bound to <description> in Hyprland. Press another shortcut."
- "Indexing finished"
- "Indexing stopped"

## Testing

- pytest:
  - `discover_start` replies from one directory read.
  - `discover_counts` batches roll up correctly.
  - `discover_children` returns `counts: null` before the walk reaches the folder.
  - The dataset rule ignores text, PDFs, camera names and ISO dates.
  - A checked dataset folder is indexed.
  - `binds_get` and `index_progress` replies.
  - A meaning-leg `results` reply keeps the jump.
  - `open` prefers the client line.
- Node:
  - `tree.js` marks at any depth.
  - A click clears the choices below the clicked folder.
  - `toRoots` produces the right excludes.
  - `keycombo` validation.
  - The new keys in `keys.js`.
- qmllint and ruff stay clean.
- Host check on a capped dev daemon, as in the #16 checks:
  - Folders step first paint and expand time on the real `$HOME`.
  - Offscreen screenshots of the Folders step, the shortcut capture, the progress popover, and an image and a PDF preview.
  - No key injection on the live overlay. `pgrep -x llama-server` is empty at the end.
