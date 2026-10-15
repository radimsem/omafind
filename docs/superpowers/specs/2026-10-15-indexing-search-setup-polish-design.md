# Indexing, search and setup polish

Date: 2026-10-15. Branch: `fix/indexing-search-setup-polish`, one pull request.

The owner used the v1 build from #19 on the live host (3440x1440, scale 1) and reported nine problems. Investigating them turned up a tenth, the watcher (A), which is the most serious. This spec fixes all ten before the v1 release. The base spec (`2026-10-11-omafind-design.md`) and the refinements spec (`2026-10-14-setup-and-search-refinements-design.md`) still hold where this one is silent.

## Goals

- The daemon uses one inotify instance and one watcher thread, however many folders are watched.
- One file that fails to embed never stops an indexing run. Every PDF page fits the embedding server's input limit.
- Indexing is measurably faster on a fixed corpus, or the speed change is dropped.
- `code:` finds code in repositories under the folders the user picked, without extra setup.
- The "matching by meaning" leg always runs once its delay has passed.
- Opening a text hit in Neovim lands on the previewed line.
- Switching between image hits never shows the fallback icon, and previews are as sharp as the preview box allows.
- The Folders step lists the folders that hold the most files first and leaves git worktrees out by default.

## Non-goals

- No change to the settings shape. `roots` with `excludes` and `codeRoots` stay as they are; only their defaults change.
- No change to ranking or to the embedding model, its flags or its context size.
- No new prefixes or search features.

## Investigation record

These findings are from 2026-10-15, measured on the live host.

| # | Report | Root cause |
|---|---|---|
| 0 | (found in the log) | `watcher.py` schedules one watchdog emitter per directory. Each emitter opens its own inotify instance and runs two threads. The live daemon had 932 inotify fds, 1,865 pipes and 1,876 threads against `fs.inotify.max_user_instances = 1024`. The journal logs `Watcher directory errno=24` (EMFILE), and directories past the limit are not watched. The same limit is shared with every other program of the user. |
| 1 | One PDF stays in progress | `matryoshka-attribution.pdf` (58 pages) indexed pages 1 to 30 and was left `partial`. Its next window failed with HTTP 500 `input (3359 tokens) is too large to process. increase the physical batch size (current batch size: 2048)`. PDF page text is embedded as one segment per page with no length limit. `Jobs.drain` re-raises any `EmbeddingError` other than a precision fault, so the whole `reindex` run exited (`reindex.log`: "Embedding request failed"). |
| 2 | Image preview flashes the fallback | `PreviewLayer.imageSource` starts on the 128 px `entry.thumb` and then changes to the original path when the `preview` reply arrives. Every source change empties the asynchronous `Image`, and the fallback icon shows whenever `status !== Image.Ready`. The cross-fade runs while the incoming layer is still empty. |
| 3 | Neovim opens at the top | The daemon sends the right line (`opener: nvim +682`, `jump` matches the highlighted preview line). `omarchy-launch-editor` passes it to `xdg-terminal-exec -e nvim +682 <path>`. Neovim with the owner's config honours `+N`, including when a last-position mark exists. The line is lost between `xdg-terminal-exec` and Neovim, most likely in Ghostty (`--gtk-single-instance=true`) forwarding the arguments to the running instance. |
| 4 | `code:` returns nothing in 0 ms | `codeRoots` is `[]` and `code.sqlite` does not exist. Code is indexed only for repositories the user switches to Code one by one, and `search_code` returns an empty reply with no reason when there is no code index. |
| 5 | "Matching by meaning" pending forever | `searchState.reduce` checks `now - started >= meaningDelay` with `Date.now()`, while the 200 ms QML `Timer` runs on the animation clock and can fire up to one frame early. The early tick sends nothing, the one-shot timer is spent and the spinner stays until the next keystroke. Separately, `RuntimeEmbedder.embed` holds `_lock` across HTTP posts, so a concurrent query's warm-up `start()` waits, and `Service._start_query` answers "the embedding server is starting" while the server is warm (4 to 5 of 10 rapid queries). |
| 6 | Batching | Inputs already go 16 per request to `/v1/embeddings`. The client has one request in flight (`_lock`), and `Jobs.drain` awaits each file's extraction before it embeds, so extraction and embedding never overlap, and a one-chunk text file is sent as a one-input request. ADR-4 measured batching at 1.5x for text on the GPU (2.2x on the CPU), 7 % for images and none for audio. |
| 7a | Folder order | `discovery.children` sorts by counts known at reply time, which are usually null early in the walk, so rows come out alphabetical. QML never re-sorts when counts arrive. |
| 7b | Worktrees | `repo` is `exists(<dir>/.git)`, which is true for the `.git` file of a linked worktree. Worktrees are tagged "repo", offered Code and indexed. |
| 8 | Blurry previews | At scale 1 the decode size equals the box. The blur comes from the 128 px thumb shown before the reply, video frames written by ffmpeg at default JPEG quality (79 to 86 measured) and scaled up from small sources, and `mipmap` smoothing on a fitted image that can sit half a pixel off. |

## A. Watcher

- Replace the per-directory watchdog emitters with one inotify instance from `inotify_simple` (pure Python, MIT, added to `helper/pyproject.toml`). One daemon thread reads it and hands events to the event loop as `_Handler` does today.
- Keep the current include logic: `_add_tree` walks allowed directories and adds one watch per directory (`IN_CREATE | IN_DELETE | IN_MODIFY | IN_MOVED_FROM | IN_MOVED_TO | IN_CLOSE_WRITE | IN_DELETE_SELF | IN_MOVE_SELF | IN_ONLYDIR`). The watch descriptor maps to its directory path, and removed or moved directories drop their watches.
- `IN_Q_OVERFLOW` marks every root dirty, so the next reconcile catches what was missed.
- `ENOSPC` from `inotify_add_watch` (the per-user watch limit) stops adding watches for that pass and logs one line with the number of unwatched directories, instead of one warning per directory. The existing `unwatched` counter keeps feeding the health report.
- `watchdog` leaves the dependencies if nothing else imports it.
- The watcher keeps its public surface (`watch`, `notice`, `flush`, `run`, `stop`, `unwatched`), so `main.py` does not change.

## B. Indexing

### B1. Embedding limits

- PDF page text goes through `extractors.chunks`, as text files do. Each chunk keeps `loc` and `loc_end` set to the page, so jumps and previews still land on the page. A page image segment keeps its OCR body cut to the same chunk length.
- `chunks` also caps a segment by an estimated token count, so dense or CJK text cannot pass 2,048 tokens with the `title: … | text: …` prefix. The cap is a module constant next to the chunk size.
- The server's error body is kept in the `EmbeddingError` message and logged once per file at WARNING, with the file id and the HTTP status but not the path or text.

### B2. Failure isolation

- In `Jobs.drain`, any `EmbeddingError` from a request that reached the server (an HTTP 4xx or 5xx reply) fails that file with `detail="embedding-failed"`, and the run continues.
- A transport error or a dead server (connection refused, process exited, timeout) still ends the run, as today, so a crashed server does not fail every remaining file.
- A `partial` file whose next window fails keeps the pages it already has and moves to `failed` with `detail="embedding-failed"`, so it no longer counts as queued.
- Failed files already count as finished in the progress popover ("92 of 92") and are listed in setup's problem list as fact tokens (`embedding-failed <path>`), as `encrypted-pdf` is today.

### B3. Throughput

- `Jobs.drain` keeps up to four extractions in flight in the existing process pool while the current file embeds, with a bounded queue. Files are written in the order they finish.
- Segments from consecutive small text files are gathered into one request of up to 16 inputs, and each file's vectors are written to its own rows.
- `RuntimeEmbedder.embed` stops holding the start/stop lock across the HTTP post. A separate semaphore allows two requests in flight.
- Measure before and after with a fixed corpus (the repo's `tests/fixtures/corpus` plus 200 Markdown files generated into the scratch home), the dev daemon and the capped scope. Record the numbers in the PR. If the gain is under 15 % for the whole corpus, revert B3 and keep A, B1 and B2.

## C. Search

### C1. Code by default

- In the Folders step, a detected repository (not a worktree) under a checked folder has Code checked by default. The user can switch it off per repository, and that choice is kept as it is today.
- The first index after setup builds `code.sqlite` for those roots.
- When there are no code roots or no `code.sqlite`, `search_code` replies with `degraded: "no-code-index"`. The overlay shows "No code is indexed yet. Turn on Code for a repository in setup." in place of the empty state, without the "Semantic search unavailable" banner.

### C2. Meaning leg

- When `reduce` returns no send because a leg is not yet due, `SearchView` restarts that leg's timer for the remaining milliseconds. The leg is sent exactly once per query.
- `Service._start_query` skips the warm-up when the embedder is already running in `text` or `full` mode, read without the lock, so a warm server never answers "starting".

## D. Open at the line

1. Reproduce: with the owner's go-ahead, run `xdg-terminal-exec -e sh -c 'printf "%s\n" "$@" > <scratch>/argv' sh +42 <file>` once, which flashes a terminal briefly, and read which arguments arrive.
2. If `+42` is dropped or re-parsed, `opener.command` passes the line in a form that survives the same probe, in order of preference: `-c 42` before the path, then the path followed by `+42`. The probe is re-run for the chosen form.
3. If the probe shows `+42` arriving intact, the cause is in the terminal's Neovim start, and the plan records the finding and stops this item for the owner.

`description()` keeps the "nvim +N" label the preview shows.

## E. Previews

### E1. Switching

- `PreviewLayer` image elements use `retainWhileLoading: true`, so a new source keeps the old frame until the new one is decoded.
- The fallback icon shows only for `Image.Error` or an empty source.
- When Qt can read the image format, the layer uses `entry.path` straight away, so the reply does not change the source.
- `PreviewLayer` gets a `mediaReady` property. `PreviewPane.show()` starts the cross-fade when the incoming layer is ready, or after 150 ms at the latest. The 120 ms fade itself is unchanged.

### E2. Sharpness

- New thumbnails are stored at 600 px on the long side, JPEG quality 90. Existing thumbs are replaced when a file is next indexed; no migration.
- Video preview frames use `scale='min(1024,iw)':-2` and `-q:v 2`.
- Preview images use `mipmap: false`, and the image is centred on whole pixels (`Math.round` on x and y).

## F. Folders step

### F1. Order

- A pure comparator in `lib/tree.js`: known total descending, then unknown counts, then zero, then the casefolded name, then the path.
- A level is sorted when its rows are inserted and once more when that root's walk reports `done`, only for levels inserted while counts were pending. It is never re-sorted on each count batch. Focus and expansion are kept by path.
- The daemon's sort stays as the first-paint order.

### F2. Worktrees

- `discovery` reads a `.git` file's `gitdir:` line, resolved against the folder. If `<gitdir>/commondir` exists, the folder is a worktree; otherwise (a submodule) it stays a repo. Rows carry `worktree: true`, and `repo` is false for them.
- The counting walk collects worktree folders and reports them in its final batch next to `datasets` (`discover_counts` gains `worktrees`).
- A worktree under a checked folder is unchecked by default through the same path as datasets (`skipped`, kept in `proposed` so a re-check sticks), so it lands in the root's `excludes`. Worktrees never get Code.

### F3. Tag colours

| Tag | Colour |
|---|---|
| repo | `Color.accent` (matches DESIGN.md) |
| worktree | `Palette.cyan` |
| dataset | `Palette.yellow` |
| secrets | `Palette.green` with the lock |
| user and other rules | `Tokens.dim` with the `Tokens.sep` border |

DESIGN.md gets the worktree line.

## IPC and docs

- `docs/ipc.md`: `discover_counts.worktrees`, the `worktree` row field, `degraded: "no-code-index"`, `detail: "embedding-failed"`.
- No settings key changes, so `settings.example.json`, `settings.py`, `lib/Settings.js` and the README table stay as they are, apart from the README's note that repositories are indexed as code by default.

## Copy

- "No code is indexed yet. Turn on Code for a repository in setup."
- Tag label: "worktree".

## Testing

- pytest:
  - The watcher over 200 directories opens one inotify fd and starts one thread.
  - Overflow marks the roots dirty, and ENOSPC logs once.
  - A PDF page over the token cap becomes several segments with the same `loc`.
  - An HTTP 500 for one file fails it and the next file is still indexed. A connection error still ends the run.
  - `search_code` with no index returns `no-code-index`.
  - `_start_query` does not report "starting" while a request holds the embedder.
  - Discovery tells a worktree from a submodule and a repo, and the walk reports worktrees.
  - Video frame argv and thumbnail size.
- node:
  - The meaning timer re-arms after an early tick and sends once.
  - The comparator ordering, and the re-sort happening once on `done`.
  - Worktrees default to skipped and repos to Code on.
  - The no-code-index empty state.
- Offscreen screenshots: image-to-image switching (several frames per switch), Folders rows with repo, worktree and dataset tags.
- Live checks after the owner repoints the plugin: `ls -l /proc/$PID/fd | grep -c inotify` is 1, the stuck PDF finishes, and `code:` returns hits.
- B3 timing before and after, as in B3.
