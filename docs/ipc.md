# UI socket

The daemon listens on `$XDG_RUNTIME_DIR/omafind/ui.sock`. The directory has mode 0700 and the socket has mode 0600. It checks `SO_PEERCRED` and closes a connection whose peer UID differs from its own.

Send one UTF-8 JSON object per line, terminated by `\n`. The line limit is 1 MiB (1,048,576 bytes), excluding the newline. An oversized or unterminated line closes the connection. Bad JSON and non-object JSON values are skipped. A supplied `v` must be the integer `1`; a version mismatch closes the connection. `hello` must include `v`.

`Service.qml` is the plugin's only socket client. It sends `hello` on every connect and reconnect. The CLI uses the same handshake for setup and status.

## Plugin to daemon

| t | Fields | Behavior |
|---|---|---|
| `hello` | `v:1` | Start the connection. Reply with the current `state` to this client. |

## Daemon to plugin

| t | Fields | Behavior |
|---|---|---|
| `state` | `v:1`, `runtime:"ready"\|"missing"`, `model:"ready"\|"missing"`, `embedder:"stopped"\|"text"\|"full"`, `build:string` | Reply to `hello`. The state shape and pushing a full state whenever a field changes are proposed. |

The scaffold implements the proposed state shape and push-on-change behavior. `runtime` checks for an executable runtime file. `model` checks that both pinned model files exist. `embedder` starts as `stopped`. Presence does not imply verified digests; `build-runtime` verifies them.

```json
{"t":"hello","v":1}
{"t":"state","v":1,"runtime":"missing","model":"missing","embedder":"stopped","build":"0.1.0+3f9a1c0d2b7e"}
```

`build` is the fingerprint of the plugin code the daemon started from: the manifest version, `+`, then the first 12 hex digits of a sha256 over `helper/uv.lock`, `helper/pyproject.toml`, `settings.example.json` and every `helper/omafindd/**/*.py`. It does not change while the daemon runs. `bin/omafind fingerprint` prints the same value for a plugin checkout.

`Service.qml` runs `bin/omafind fingerprint` once when the plugin loads. When a `state` carries a different `build`, or none (a daemon older than this field), it runs `bin/omafind setup` once for that plugin build. A daemon that exits on a missing dependency sends no `state`, so after the third failed connect `Service.qml` runs `bin/omafind status --json` and treats a `stale` or `missing` venv the same way. A daemon that cannot fingerprint its own code reports `build:""`. Setup syncs the venv to the lock file and restarts the unit, and the plugin reconnects. While setup runs, the search view shows an `update-running` card ("omafindd is updating to match the installed plugin."). Setup runs as `bin/omafind setup --json`, whose last stdout line is `{"ok":true,"build_missing":[...]}` or `{"ok":false,"error":{...}}` (see Errors). If setup fails, the search view shows the error's title and detail in an `update-failed` card, with Retry and any Install packages or Open log action. It runs setup again only on Retry or for a newer plugin build. A `state` with the plugin's build clears the failure.

## Errors

Every failure the plugin shows is one error object. The daemon writes its copy in `helper/omafindd/errors.py`, one constructor per code.

```json
{"code":"build-missing-packages","title":"The search engine could not be built.","detail":"Missing build packages: vulkan-headers. Install them, then press Retry.","fix":{"kind":"install","packages":["vulkan-headers"]},"log":"/home/u/.local/share/omafind/cache/logs/build-runtime.log"}
```

| Field | Value |
|---|---|
| `code` | Stable kebab-case string. The plugin branches on it, never on the text. |
| `title` | One sentence: what happened. |
| `detail` | One or two sentences: why, then what to do next. It names plugin controls ("press Retry"), never CLI commands. May be `""`. |
| `fix` | Optional. `{"kind":"install","packages":[...]}` or `{"kind":"retry"}`. |
| `log` | Optional. Absolute path of the log that holds the full cause. |

The object has no other fields. Facts a view shows as tokens, such as `free_gb` or a file count, stay on the message that carries the object.

- `fix.kind:"install"`: `packages` are Arch repository names without duplicates. The plugin offers Install packages, which runs `omarchy-launch-floating-terminal-with-presentation omarchy-pkg-add <packages>`, and shows `sudo pacman -S --needed <packages>` with Copy. It then runs `omarchy-pkg-present <packages>` every 2 s for up to 10 minutes and retries when it succeeds. Install packages stays pressable while it waits, to open the terminal again. Retry, a new code, a cleared error or a closed view stops the wait.
- `fix.kind:"retry"`: the view's own retry control is the fix. Step 1 of setup uses its footer button, labelled Retry. Every other card (search banner, Folders and Index steps, drive dialog, open toast) puts Retry on the card, also next to an install fix, whose detail says "then press Retry". An open toast whose error has a fix stays until Retry or Dismiss.
- `log`: the plugin offers Open log, which runs `omarchy-launch-editor <log>`. Logs live in `<data>/cache/logs/` (`build-runtime.log`, `llama-server.log`, `omafindd-start.log`) and at `<data>/index/reindex.log`. `<data>` is `$XDG_DATA_HOME/omafind`, by default `~/.local/share/omafind`.

An error travels in one of three places:

- A `{"t":"error",...}` reply or broadcast. The object's fields sit at the top level next to the routing key: `for` (setup requests and `open`), `seq` (search) or `id` (preview and open).
- A field named `error` on `runtime_progress`, `warm_failed`, `open_failed`, `paused`, `discover_counts`, `discover_children` and `fs_list`, and each item of `progress.tool_errors`.
- `results.degraded`.

`code` follows the cause, not the request that hit it. An exception no handler expects becomes `internal`, with the exception text as the cause.

Tone is the card color: red (`Color.urgent`) for a failure, yellow (`Palette.yellow`) for a degraded or paused state. `tone()` in `lib/errors.js` returns `urgent` or `warn`. `<cause>` is one clause from the failing call (an HTTP status and message, an OS error, the first error line of a log), at most 200 characters and never a secret. The tests pin the copy rules, not these strings; `errors.py` wins when they differ.

| Code | Tone | Title | Detail | Fix | Log |
|---|---|---|---|---|---|
| `tools-missing` | red | Some tools omafind needs are missing. | Missing: `<packages>`. Install them, then press Retry. | install | |
| `helper-install-failed` | red | The omafind helper could not be installed. | `<cause>`. Press Retry to try again. | retry | |
| `build-missing-packages` | red | The search engine could not be built. | Missing build packages: `<packages>`. Install them, then press Retry. | install | `build-runtime.log` |
| `build-failed` | red | The search engine could not be built. | `<first error line>`. Open the log for the full output, then press Retry. | retry | `build-runtime.log` |
| `build-no-scope` | red | The search engine could not be built safely. | The systemd user memory scope is unavailable, so the build would run without a memory cap. Log out and back in, then press Retry. | retry | |
| `model-download-failed` | red | The model could not be downloaded. | `<cause>`. Check the network connection, then press Retry. | retry | |
| `model-verify-failed` | red | The downloaded model is damaged. | `<file>` does not match its checksum. Press Retry to download it again. | retry | |
| `server-start-failed` | red | The embedding server did not start. | `<cause>`. Showing keyword matches until it starts. | retry | `llama-server.log` when known |
| `server-starting` | yellow | The embedding server is starting. | Showing keyword matches until it is ready. | | |
| `embedding-unavailable` | yellow | Search by meaning is unavailable. | `<cause>`. Showing keyword matches. | retry | `llama-server.log` when known |
| `index-running` | yellow | Indexing is running. | Showing keyword matches until it finishes. | | |
| `disk-low` | yellow | Indexing is paused. | Free some disk space and indexing resumes by itself. | | |
| `index-exited` | red | Indexing stopped. | The indexer exited with code `<n>`. Open the log for the cause, then press Retry. | retry | `index/reindex.log` |
| `no-roots` | red | No folders are selected. | Pick at least one folder to index. | | |
| `drive-not-mounted` | red | `<drive>` is not connected. | Connect it, then press Retry. | retry | |
| `scan-failed` | red | `<folder>` could not be scanned. | `<cause>`. Press Retry to scan it again. | retry | |
| `binds-failed` | red | Your Hyprland bindings could not be read. | `<cause>`. The shortcut was not saved. | retry | |
| `no-index` | red | Nothing is indexed yet. | Open setup and start the first index. | | |
| `file-missing` | red | `<name>` is missing. | It was moved or deleted after it was indexed. | | |
| `open-failed` | red | `<name>` could not be opened. | `<cause>`. | retry | |
| `tool-missing` | red | `<n>` files need `<tool>`. (1 file needs `<tool>`.) | They could not be indexed without `<what>`. Install `<package>` and they are indexed again. (1 file: It could not be indexed without `<what>`. Install `<package>` and it is indexed again.) | install | |
| `bad-request` | red | omafind sent a request the service did not understand. | `<cause>`. Restart the overlay and try again. | | |
| `internal` | red | Something failed inside the omafind service. | `<cause>`. | retry | |
| `daemon-offline` (plugin) | red | The omafind service is not running. | It did not answer on its socket. Press Retry to start it. | retry | `omafindd-start.log` when it exists |
| `update-running` (plugin) | yellow | omafindd is updating to match the installed plugin. | Search returns when it restarts. | | |
| `update-failed` (plugin) | red | omafindd did not update. | `<setup error>`. Press Retry to try again. | retry | |
| `unknown` (plugin) | red | `<string>` | `""` | | |

The plugin writes copy for four codes only, because no daemon reply exists for them:

- `daemon-offline` (`lib/errors.js`): the socket does not answer. Its Open log points at `omafindd-start.log`, which the daemon writes when it fails to start (a failed import or socket bind) and removes once its socket is up.
- `update-running` and `update-failed` (`lib/Update.js`): `bin/omafind setup` is bringing the daemon to the plugin's build, or it failed. The daemon is restarting, so it cannot write the copy.
- `unknown`: a daemon older than this section. During an update a new plugin can briefly talk to a daemon that still sends a bare string (`reason`, or a string `degraded` or `error`). The plugin wraps it as `{"code":"unknown","title":"<string>","detail":""}`. The daemon restarts with the plugin update, so this lasts until then.

`bin/omafind setup --json` prints `{"ok":true,"build_missing":[...]}` or `{"ok":false,"error":{...}}` as its last stdout line. Setup fails only with `tools-missing` (a runtime tool is missing) or `helper-install-failed` (a setup step failed, or the socket stayed silent). Missing build packages never fail setup: while the runtime binary is missing, `build_missing` lists them and stderr says so, and the engine step reports `build-missing-packages` before it builds.

## Search and warm-up (issue #2)

These shapes are proposed. After `hello`, a connection may send:

```json
{"t":"warm"}
{"t":"search","seq":7,"q":"invoice 4412","legs":["words","meaning"],"limit":40}
```

`warm` starts the text-mode embedder and replies with the current `state`, or
`{"t":"warm_failed","error":{"code":"server-start-failed","title":"The embedding server did not start.","detail":"It did not answer within 60 s. Showing keyword matches until it starts.","fix":{"kind":"retry"},"log":"/home/u/.local/share/omafind/cache/logs/llama-server.log"}}`.
After `warmMinutes` without a query the embedder stops. Each query resets this
timeout. `warmMinutes:0` stops it immediately after the reply.

The CLI holds an exclusive lock on `~/.local/share/omafind/index.lock` during
reindex. The daemon probes it with a non-blocking shared flock before starting
a server. While reindex holds the lock, all searches use `legs:["words"]` and
a `degraded` error with code `index-running`, including requests for meaning only.
`warm` replies `warm_failed` with the same `index-running` error.
The daemon keeps its shared lock until its server stops. Reindex first tries
the exclusive lock without blocking. If it is busy, reindex prints
`waiting index.lock` once on stderr, holds an exclusive lock on
`~/.local/share/omafind/index.want`, then waits for `index.lock`.
The daemon probes both files without blocking on each 0.5 s tick. When
`index.want` is held, it stops its server and releases the shared lock. Reindex
keeps `index.want` held through server shutdown and the end of the run, so the daemon stays
words-only until indexing ends.
Incremental reindexes that the daemon starts share its server instead. The daemon
warms it in `full` mode, keeps its shared locks, and passes the server address to
the child, which takes `index.lock` shared and never starts or stops a server.
Searches keep the meaning leg during such a run, and the idle timeout waits for
the child to exit. A standalone `omafind reindex` still waits for exclusive
ownership as above.
Words-only searches do not wait for server startup or embedding requests.
When a meaning query needs a cold server, it starts warming in the background
and replies immediately with `legs:["words"]` and a `degraded` error with code
`server-starting`, including requests for meaning
only. This also applies while an explicit `warm` request is still starting the
server, and after reindex releases its lock. A later identical query returns
the requested legs once the server is warm. A startup failure is a
`server-start-failed` error with the cause and the `llama-server.log` path, in
`warm_failed.error` for `warm` or in `results.degraded` for a query.
After the `hello` reply, requests on one connection run concurrently. Search
replies may arrive in any order; clients use `seq` to match them to requests.

A search gets exactly one reply. `seq` is an integer, `q` a string, `legs` a
nonempty array of `words` and/or `meaning`, and `limit` an integer 1..200.
Omitted legs mean both; an omitted limit uses `maxResults` (default 40).
Optional `kinds` is an array of `text`, `pdf`, `image`, `video` and/or
`audio`. Other types or unknown kinds return `bad-request`. Omission searches
every kind. An empty array matches nothing. Multiple kinds form a union;
a textual prefix (`doc:`, `pdf:`, `img:`, `vid:` or `aud:`) narrows it to that
kind. Any other word before a colon, such as `code:`, is part of the query.
Filtering happens before candidate budgets, the result limit, `total` and
`weaker` are computed.
A client may repeat `seq` with words-only then both legs. For one `seq`, a reply
whose `legs` include `meaning` supersedes words-only regardless of arrival order.
Results are flat in score order; grouping is client-side in #4.

```json
{"t":"results","seq":7,"legs":["words","meaning"],"ms":{"embed":14,"scan":9,"words":4,"total":31},"total":17,"weaker":3,"degraded":null,"items":[{"id":"b81e:812:900","kind":"pdf","path":"/home/u/a.pdf","name":"a.pdf","dir":"/home/u","volume":"<uuid>","label":"root","drive":false,"offline":false,"loc":12,"loc_end":null,"leg":"meaning + words","part":"text","z":3.4,"score":7.4,"weak":false,"hits":["invoice","4412"],"snippet":[{"t":"due on ","m":false},{"t":"invoice","m":true}],"thumb":null,"mtime":1760000000,"size":48211,"info":{}}]}
```

`id` is opaque, resolved only against that connection's latest results.
`drive` is true for content volumes other than the volume holding `$HOME`.
Drive items carry their stored `label` and a `dir` relative to the mount,
prefixed by `/`, whether online or offline. Internal-volume items carry
`drive:false` and an absolute `dir`. Online `path` remains the absolute file path.
`offline` reflects the volume mount state. `loc` is a 1-based
line or PDF page, or seconds for video and audio; images have a null location.
`loc_end` is the next kept frame's second or the audio window's end second.
Extracted HTML/docx/odt set `info.extracted:true`. `part` is `text`, `image`
(an image or rendered PDF page), `name`, `ocr` (an OCR body match), `frame`,
`speech` (a video soundtrack) or `audio`. `z` is null for words-only
results. `weak` means score below half the top score. `total` counts qualified
files before the limit; `weaker` counts weak items in the returned list.
`degraded` is null or an error object (see Errors): `server-starting`,
`index-running`, `server-start-failed` or `embedding-unavailable`. Embedding
failures still return words.
Timing fields are milliseconds.

Error replies carry `seq` and the error fields, for example
`{"t":"error","seq":7,"code":"no-index","title":"Nothing is indexed yet.","detail":"Open setup and start the first index."}`.
Invalid search arguments reply `bad-request`. An exception while handling a
request replies `internal` with the exception as the cause, such as
`{"t":"error","seq":7,"code":"internal","title":"Something failed inside the omafind service.","detail":"No such table: meta.","fix":{"kind":"retry"}}`,
and leaves the connection open for the next request. `seq` echoes the request.
The CLI sends seq 1 with both legs and prints the complete results object for
`--json`. It exits 0 for any result, 1 for no index or a service error, 2 for bad arguments, and
3 for a silent socket.

Settings in the plugin's shell.json entry are `setupDone` (bool, default false),
`gpu` (`"auto"` or `"never"`, default `"auto"`), `audio`, `roots` (default `[]`),
`ignoredVolumes` (default `[]`, see Volumes), `maxResults` (10..200, default 40),
`warmMinutes` (0..60, default 5), `imageBudget` (70, 140 or 280, default 140)
and `shortcut`. [settings.md](settings.md) has the full table. Invalid paths are dropped;
budgets are not coerced. A `codeRoots` key left by an older plugin is ignored.
`audio` (bool, default true) controls audio files and video soundtracks.
With audio off, audio files have state `skipped` and code `audio-off`.
Silent audio has code `silent-audio`. A failed soundtrack leaves frame vectors
in state `partial`, with a failure detail; it is retried on an explicit reindex.
`info.thumb` and `thumb` contain a cached JPEG path in `thumbs/<volume-uuid>/`.
There is no editor setting; openers read the Omarchy default editor.
`shortcut` is a string, default `"SUPER + E"`. It is one or more uppercase
modifiers (`SUPER`, `SHIFT`, `CTRL`, `ALT`) followed by `+` and an uppercase key
name (letters, digits or underscores), or a lone function key `F1` to `F35`.
Duplicate modifiers and a modifier used as the key are invalid. Invalid values
fall back to the default.

## Overlay (issue #4)

After `hello`, the plugin may send:

| t | Fields | Behavior |
|---|---|---|
| `preview` | `id`, `q` (string, default `""`) | Render the selected result on demand. Unknown IDs or missing online files reply `error` with `id` and a `file-missing` error. |
| `open` | `id`, `how:"open"\|"reveal"` (default `"open"`), optional `line` (int ≥ 1) | Open text at `line`, else at the preview jump, else at the chunk start; other kinds ignore `line`. `how:"reveal"` selects the file with detached `nautilus --select`. Offline and missing files run nothing. A bad `how` or `line` replies `error` with `for:"open"`, `code:"bad-request"`. |
| `status` | none | Reply with current indexed-file and queue counts. |

| t | Fields | Behavior |
|---|---|---|
| `preview` | `id`, `mode:"lines"\|"image"\|"bars"`, `lines:[{no,text,hit}]`, `jump`, `range:[first,last]\|null`, `image:path\|null`, `bars:[int]`, `opener`, `editor` (text only) | Text uses a clamped ±8-line window. PDF/video render the selected page/second; online images use the source file, or a cached `magick` still at 1200 x 840 when Qt cannot decode the format (HEIC, AVIF, RAW); PDF pages render 1200 px on the long side. Audio has 64 RMS bars in 0..100. Unused arrays are empty. Offline items use mode `image` with their cached thumbnail or null. |
| `opened` | `id`, `opener`, `at:string\|null` | Human command label and location: `mpv --start=872`/`14:32`, `omarchy-launch-browser`/`p. 37`, `nvim +212`/`L212`; images and reveals have null `at`. |
| `open_failed` | `id`, `error` | The file cannot be opened: `drive-not-mounted` for a file on an unplugged drive, `file-missing` for a missing file or an unknown ID, `open-failed` with the cause when the opener fails to start. |
| `error` | `id`, `for:"open"`, error fields | `bad-request` for invalid open arguments, `internal` for an unexpected exception. A failed preview replies `error` with `id` and no `for`. |
| `status` | `files`, `roots`, `offline:[]`, `done`, `total` | Counts from all index stores. Also pushed when changed, at most once every 0.5 seconds. |

IDs resolve only against that connection's latest `results`; a `results` reply with a new `seq` clears
its remembered preview jumps; the meaning leg of the same `seq` keeps the jumps of ids it still lists. `editor` is the basename of the first command in
`~/.local/state/omarchy/defaults/editor`, falling back to `nvim`. Opener labels
come from the same command selection used to open the file. Extracted documents
retain the existing opener behavior (no editor line argument).
Each connection runs at most one preview render at a time. A newer preview
supersedes pending requests and suppresses replies and jumps from older requests.
Direct mpv, xdg-open and nautilus launches use `uwsm-app --`, falling back to
`systemd-run --user --scope --quiet --collect --` when uwsm-app is absent.

Indexing runs in a separate CLI process. The daemon polls committed store counts
every 0.5 seconds: `files` counts non-null `indexed_at`, `total` counts tracked
files and `done` excludes pending files and partial files with no failure detail.
With no queued work, `done` equals `total`. `roots` counts configured `roots`;
`offline` lists labels of unmounted content volumes. No text is retained by previews; extracted text
temporaries are deleted after rendering. PDF/video images are cached under
`$XDG_RUNTIME_DIR/omafind/preview/`, keyed by source path, mtime, page/second and render size; image stills live there too.
Images are rendered to temporary paths and atomically published. Audio bars
decode at 400 Hz and use a 32-entry memory cache keyed by path and nanosecond
mtime. Status counts run off the event loop and are reused while store and WAL
mtimes stay unchanged; the root count still follows current settings.

```json
{"t":"preview","id":"b81e:812","q":"where they tal"}
{"t":"preview","id":"b81e:812","mode":"lines","lines":[{"no":212,"text":"where they talk","hit":true}],"jump":212,"range":[204,220],"image":null,"bars":[],"opener":"nvim +212","editor":"nvim"}
{"t":"open","id":"b81e:812","how":"open"}
{"t":"open","id":"b81e:812","how":"open","line":212}
{"t":"opened","id":"b81e:812","opener":"mpv --start=872","at":"14:32"}
{"t":"open_failed","id":"b81e:812","error":{"code":"drive-not-mounted","title":"Photos2024 is not connected.","detail":"Connect it, then press Retry.","fix":{"kind":"retry"}}}
{"t":"status"}
{"t":"status","files":3880,"roots":4,"offline":[],"done":1204,"total":1209}
```

## Setup (issue #5)

| Request t | Reply t | Fields |
|---|---|---|
| `runtime_status`, `runtime_install`, `runtime_pause` | `runtime_progress` | none |
| `discover_start` | `discover_result` | optional `volume` UUID |
| `discover_children` | `discover_children` | `path` absolute folder |
| (broadcast) | `discover_counts` | sent while a walk runs |
| `discover_stop` | `discover_stop` | stops this connection's discovery |
| `binds_get` | `binds` | none; reads `hyprctl binds -j` and the Omarchy menu file |
| `fs_list` | `fs_list` | `path` absolute path or `~`/`~/...` |
| `index_start` | `progress` | none; rereads current settings |
| `index_progress` | `progress` | none; reads the stores and returns the latest snapshot without starting a run |
| `retry_failed` | `retry_failed` | `code` a per-file failure code; the plugin sends `tool-missing` |

All paths on the wire are absolute, except `excludes`, which are POSIX paths relative to their root. Requests may pass `"~"` or `"~/x"`; the daemon expands them and echoes the request string in `root`/`path` and the absolute path in `abs`. Every discovery `counts` object carries `text, pdf, image, video, audio, dirs` (zeros included). Every request below gets exactly one reply; failures reply `{"t":"error","for":"<request t>",...}` with the error fields (see Errors) and never carry `seq` or `id` (Service.qml routes errors on `for` first).

New messages are accepted only after `hello`, like `search`.

```
plugin: {"t":"runtime_status"}
plugin: {"t":"runtime_install"}
plugin: {"t":"runtime_pause"}
daemon: {"t":"runtime_progress","state":"idle|running|paused|failed|done",
         "step":"build|download|null","file":"model|mmproj|null","done":512,"total":865,"unit":"MB",
         "left_seconds":60|null,"error":null|{error},
         "build":{"state":"wait|run|ok|failed","seconds":192|null,"tag":"b11461","backend":"Vulkan","gpu":"RTX 3060 12 GB"|null},
         "files":{"model":{"name":"embeddinggemma-2-Q8_0.gguf","state":"wait|run|verify|ok","done":310,"total":310},
                  "mmproj":{"name":"mmproj-embeddinggemma-2-Q8_0.gguf","state":"wait|run|verify|ok","done":202,"total":555}}}
```
- Reply to all three requests is a `runtime_progress` snapshot. While a job runs the daemon also broadcasts it to every ready client, at most twice per second, plus once on every state change.
- MB are decimal and rounded: 309,855,456 B is 310, 554,821,024 B is 555, `total` is `round(sum bytes / 1e6)` = 865. `done` sums both files.
- `state:"done"` means the runtime is built and both digests verified. `files.*.state:"ok"` means sha256 verified (cached by size and mtime, so `runtime_status` hashes at most once per daemon start, in a thread). `build.seconds` is null when the runtime existed before this daemon started.
- `runtime_install` while `running` is a no-op snapshot. While `paused` or `failed` it resumes.
- `error` is null unless `state` is `failed`. Its code is `build-missing-packages`, `build-failed`, `build-no-scope`, `model-download-failed`, `model-verify-failed` or `internal`. Before it spawns the build, the daemon checks the build packages (`tools.BUILD_NEEDS`: `vulkan-headers`, `shaderc`, `gcc`, `git`, `uv`) and fails with `build-missing-packages` without starting it. The build writes its stdout and stderr to `<data>/cache/logs/build-runtime.log`, replaced at each run, and a build error carries that `log`. A failed build leaves `files.*.state` as it was.

```
plugin: {"t":"discover_start"}                      // $HOME plus every non-system volume
plugin: {"t":"discover_start","volume":"<uuid>"}    // one volume only (#6 new-drive flow)
daemon: {"t":"discover_result","volume":null,"home":"/home/u","device":"gpu",
         "rates":{"gpu":{"text":0.07,"pdf":0.37,"image":0.14,"video":3.2,"audio":1.5},
                  "cpu":{"text":0.13,"pdf":0.54,"image":1.36,"video":18.0,"audio":11.1},
                  "bytes":{"text":11000,"pdf":48000,"image":7000,"video":40000,"audio":12000}},
         "roots":[{"path":"/home/u","volume":"<uuid>"},{"path":"/run/media/u/USB","volume":"<uuid>"}],
         "folders":[{"path":"/home/u/Documents","name":"Documents","xdg":true,"repo":false,"worktree":false,"hasChildren":true,"volume":"<uuid>"},
                    {"path":"/home/u/omaone","name":"omaone","xdg":false,"repo":true,"worktree":false,"hasChildren":true,"volume":"<uuid>"},
                    {"path":"/run/media/u/USB","name":"/run/media/u/USB","xdg":false,"repo":false,"worktree":false,"hasChildren":true,"volume":"<uuid>"}]}
```
- The reply comes after one directory read per root (plus one peek per folder for `hasChildren`). `folders` lists the folders directly under `$HOME`, sorted by name, then one row per volume mounted outside `$HOME`; with `volume` it lists the folders under that volume's mount. At most 500 home folders, plus the volume rows. A volume-only request lists at most 500 folders.
- Symlinks, hidden names, the heavy and vendor names in `rules.HEAVY_GLOBS` and secret names are never listed. `xdg` is true for the Documents, Pictures, Videos, Music, Download and Desktop folders of `user-dirs.dirs`. `repo` is true when the folder holds a `.git` directory or a submodule; `worktree` is true for a linked git worktree, and `repo` is false for it.
- `rates` lets the client estimate index size and time for any counts on `device`.
- After the reply the daemon walks each root once with `fd` (one pass over the indexable kinds, no hidden paths, heavy names or secrets) and broadcasts `discover_counts`. A walk of the same root that is running, or finished successfully less than 300 s ago, is reused: the daemon broadcasts its counts so far as one `discover_counts` instead of walking again. The overlay sends `discover_stop` when its picker closes. Walks stop when their last interested connection stops discovery or disconnects, or when the daemon stops.

```
daemon: {"t":"discover_counts","root":"/home/u","done":false,"seconds":null,
         "counts":{"/home/u/Documents":{"text":745,"pdf":67,"image":26,"video":0,"audio":0,"dirs":4}}}
daemon: {"t":"discover_counts","root":"/home/u","done":true,"seconds":1.4,"counts":{...},
         "datasets":[{"path":"/home/u/Pictures/frames","kind":"image","files":1418,"named":96}],
         "repos":["/home/u/omaone"],"worktrees":["/home/u/omaone-wt"]}
```
- A fresh walk starts with `counts:{}`, `done:false`, `seconds:null`, and `reset:true`. Clients clear that root's previous counts, datasets, and child replies; a reused walk replays a snapshot without `reset`.
- Sent about every 250 ms with the folders whose counts changed since the last batch. `counts` are rolled up: a folder counts every indexable file below it. `dirs` counts the rolled-up directories containing those files, including the folder itself; it never contributes to file totals. A folder the walk never reached has no entry; once `done` is true a missing folder has zero files.
- The last batch has `done:true`, `seconds` rounded to 0.1, and `datasets`: media folders with 300 or more files of one kind (image, video or audio) of which at least 70% are machine-named; `named` is that share in percent. `repos` and `worktrees` are sorted lists of the absolute paths of the git repositories and linked worktrees the walk found. A done snapshot of a reused walk carries `datasets`, `repos` and `worktrees` too. A failed walk still ends with `done:true` and adds `error`, a `scan-failed` error whose cause is the last error line from fd or the OS reason. Failed walks are never cached, so the next discovery request retries. Folder and file names that cannot be encoded as UTF-8 are skipped.

```
plugin: {"t":"discover_children","path":"/home/u/Pictures"}
daemon: {"t":"discover_children","path":"/home/u/Pictures","volume":"<uuid>","error":null,
         "dirs":[{"path":"/home/u/Pictures/frames","name":"frames","repo":false,"worktree":false,"hasChildren":false,
                  "counts":{"text":0,"pdf":0,"image":1418,"video":0,"audio":0,"dirs":1},
                  "rule":"dataset","evidence":{"kind":"image","files":1418,"named":96}},
                 {"path":"/home/u/Pictures/2024","name":"2024","repo":false,"worktree":false,"hasChildren":true,
                  "counts":null,"rule":null,"evidence":null}]}
```
- One level, same filters as `folders`, sorted by indexable files (descending), then by name. `counts` is null until the walk reaches the folder; the counts arrive later in `discover_counts`. Paths under a known root reuse its walk and volume UUID without probing the mount again, even after that walk is older than 300 s; only `discover_start` walks a root again. A path outside every known root starts a walk scoped to that path, even when its volume mount is higher up. `/`, `/proc`, `/sys`, `/dev`, `/run`, and paths below these pseudo-filesystem roots are refused with `bad-request`; a known mounted volume below `/run` can still be expanded. `volume` is the UUID of the volume holding `path`, or null. An unreadable folder replies `dirs:[]` with `error` set to a `scan-failed` error naming the OS reason. A request still running when its connection sends `discover_stop` replies `{"t":"discover_stop"}` instead, and the plugin forgets every children request in flight when it stops discovery.


```
plugin: {"t":"fs_list","path":"~"}
daemon: {"t":"fs_list","path":"~","abs":"/home/u","dirs":["Documents","Pictures"],"error":null}
```
- Sorted case-insensitively, dot dirs and `rules.HEAVY_GLOBS` names left out, at most 500 names. A path that is missing, is not a folder or cannot be read gets `dirs:[]` and `error`, a `scan-failed` error naming that cause, instead of an `error` reply.

```
plugin: {"t":"binds_get"}
daemon: {"t":"binds","binds":[{"chord":"Super Shift Space","description":"Launcher"},{"chord":"F9","description":""}],"menu":true}
```
- `menu` is true when the "Find files" row (the `// omafind-menu-start` block that `bin/omafind bindings menu add` writes) is in `$XDG_CONFIG_HOME/omarchy/extensions/omarchy-menu.jsonc`. A missing file or broken markers read as false.
- Live global binds, with modifiers ordered Super, Ctrl, Shift, Alt, then the key (`Space`, `Comma`, `Period`, `Return`, `Escape`, `Tab`, `F1` to `F35`, letters and digits). Submap binds, empty keys and omafind's own bind are left out. The first description per chord wins. A failure replies `error` with `for:"binds_get"` and `code:"binds-failed"`.

```
plugin: {"t":"index_start"}
daemon: {"t":"progress","running":true,"done":612,"queued":597,"volume":"<uuid>","device":"gpu","vram_gb":0.9,
         "kinds":{"text":{"done":734,"total":734},"pdf":{"done":31,"total":49,"pages":412},
                  "image":{"done":51,"total":420,"ocr":63},"video":{"done":0,"total":6},"audio":{"done":0,"total":0}},
         "skipped":{"size-cap":2},"failed":{"encrypted-pdf":1,"tool-missing":12},
         "problems":[{"path":"/home/u/Documents/a.pdf","code":"encrypted-pdf","detail":""}],
         "tool_errors":[{"code":"tool-missing","title":"12 files need tesseract.",
                         "detail":"They could not be indexed without text recognition. Install tesseract and they are indexed again.",
                         "fix":{"kind":"install","packages":["tesseract"]}}]}
```
- `index_progress` replies the same `progress` body and starts nothing, so a view can fill before the next broadcast.
- Reply to `index_start` is a `progress` snapshot. Then the daemon broadcasts `progress` at most twice per second while the index job runs, and once more when it exits (`running:false`). `status` keeps working unchanged for the #4 footer.
- When the child exits non-zero, the final `progress` includes `exit:<code>` (negative for termination by a signal). The daemon then broadcasts exactly one `error` with `for:"index_start"` and code `index-exited`, whose detail names the exit code and whose `log` is the absolute `<data>/index/reindex.log` path. These broadcasts report failure after the initial reply; they carry no `seq` or `id`. Successful completion omits `exit` and sends no error.
- `device` is `gpu`, `cpu` or null; `vram_gb` is a float or null (unknown is null, the client hides the token). `skipped` and `failed` omit zero keys. Secrets are never listed, so they are not counted in `skipped`. `problems` lists at most 50 failed files.
- `problems` items are `{path, code, detail}`, and `failed` counts files by the same `code`. Per-file codes are kebab-case: `encrypted-pdf`, `timeout`, `extract-failed`, `embedding-failed`, `embedding-precision-fault`, `soundtrack-failed`, `audio-off`, `silent-audio`, `tool-missing`. `detail` is the extractor's own message; for `tool-missing` it names the tool.
- `tool_errors` holds one `tool-missing` error per missing tool, each with an install fix for that tool's package. It is `[]` when no file waits on a tool.
- A file whose embedding the server rejects gets code `embedding-failed`: state `failed`, or, for a `partial` file whose earlier pages are already indexed, state `partial` with that detail. The halted file stays searchable up to where it stopped and leaves the queue.
- `kinds.image.ocr` counts ready images with a non-empty OCR text segment (`kind:"ocr"`); filename and parent-folder text in `name` segments does not count.
- Error codes on these `error` replies: `no-roots` (settings have no roots), `bad-request`, `scan-failed`, `drive-not-mounted` (a drive scan whose drive is gone), `binds-failed`, `index-exited` and `internal`. Runtime job failures arrive in `runtime_progress.error`, not as `error` replies.

```
plugin: {"t":"retry_failed","code":"tool-missing"}
daemon: {"t":"retry_failed","code":"tool-missing","count":12}
```
- Marks every file whose last failure has `code` as stale, so the running pass or the next one indexes it again. `count` is the number of files marked. The plugin sends it when an install fix on a `tool-missing` error succeeds.

The daemon owns the runtime job: closing a view or disconnecting a client does
not pause it. Build pause terminates the build process group; resume reruns the
idempotent script. Download pause leaves `.part` files for HTTP Range resume.
The daemon refuses to build without a systemd user memory scope.

Indexing runs as a `bin/omafind reindex --incremental` child in a new session.
The daemon reads committed store counts every 0.5 s.
The child logs to `<data>/index/reindex.log` (0600, replaced for each run), writes
skip counts to `run.json`, and is terminated when the daemon stops. `status` retains the issue #4 footer shape.

Later issues append their messages here.

## Volumes, freshness and disk (issue #6)

After hello, the daemon sends state, then one `volume` for each online unknown,
non-ignored drive, then `paused` if disk indexing is paused. Known drives are
never replayed. Mount changes are broadcast to all ready clients. Labels fall
back to the mount basename, then the UUID. `size` is bytes; `fs` is the filesystem
name from lsblk. Offline mounts are null.

```json
{"t":"volume","uuid":"6BFF-B220","label":"Photos2024","fs":"exfat","size":1800000000000,"mount":"/run/media/u/Photos2024","online":true,"known":false}
{"t":"drive_decision","uuid":"6BFF-B220","choice":"scan"}
{"t":"drive_decision","uuid":"6BFF-B220","choice":"ignore"}
{"t":"reconcile","uuid":"6BFF-B220","label":"Photos2024","done":120,"total":900}
{"t":"paused","error":{"code":"disk-low","title":"Indexing is paused.","detail":"Free some disk space and indexing resumes by itself."},"free_gb":1.4,"need_gb":2}
{"t":"resumed"}
```

`drive_decision` is a plugin request with `choice:"scan"|"ignore"`. The daemon
replies once with the same three fields. Scan leaves discovery to the dialog;
ignore suppresses further announcements for this session. The client persists
`ignoredVolumes`, an array of non-empty filesystem UUID strings, default `[]`.
The daemon rereads that setting; it does not write shell.json.

A returning known drive gets `volume` with `known:true`, followed by size/mtime
reconciliation. `reconcile` is pushed at most twice per second, plus a final
snapshot with `done == total`. An unplugged known drive gets `online:false` and
`mount:null`, followed by a fresh status. Internal roots share one inotify instance
and reader thread, with a two second directory coalescing window. Removable drives reconcile on mount.

Disk free space is checked every 30 seconds and before every indexing kick;
the child checks it before each batch. Below 2,000,000,000 bytes it pauses;
at or above the threshold it resumes. `free_gb` is decimal GB rounded to one
place. Paused and unverified-model kicks do not start a child. Changes arriving
while a child runs are deferred and processed after it exits.

```json
{"t":"discover_start","volume":"6BFF-B220"}
{"t":"discover_result","volume":"6BFF-B220","roots":[{"path":"/run/media/u/Photos2024","volume":"6BFF-B220"}],"folders":[]}
{"t":"index_start","volume":"6BFF-B220"}
{"t":"progress","running":true,"done":612,"queued":597,"volume":"6BFF-B220","volumes":{"6BFF-B220":{"label":"Photos2024","done":612,"total":1209}},"device":null,"vram_gb":null,"kinds":{"text":{"done":612,"total":1209},"pdf":{"done":0,"total":0,"pages":0},"image":{"done":0,"total":0,"ocr":0},"video":{"done":0,"total":0},"audio":{"done":0,"total":0}},"skipped":{},"failed":{},"problems":[],"tool_errors":[]}
{"t":"status","files":3880,"roots":4,"offline":["Photos2024"],"done":1204,"total":1209}
```

`discover_result` echoes `volume`, null for an unscoped request. `roots[0].path` is the drive mount. The drive picker checks every top folder and uses the same lazy children and counts messages described above. Dataset evidence arrives in the final counts batch.

`index_start.volume` is optional and selects `reindex --incremental --volume
<uuid>`; omission runs all configured volumes. `progress.volumes` holds one
`{label,done,total}` object per content store keyed by UUID. Progress and status are pushed while counts advance
and on child exit, so the indexed footer and open list follow watcher updates.
`status.offline` lists stored labels for known content volumes absent from the
current mounts.

Offline stores stay searchable, including meaning search when the verified
model is ready. Their items retain the cached thumbnail and carry these fields:

```json
{"offline":true,"drive":true,"label":"Photos2024","volume":"6BFF-B220","path":"/run/media/u/Photos2024/docs/note.txt","dir":"/docs"}
```

`path` is last mount plus stored relative path; drive `dir` is the relative
parent prefixed by `/`. Online drive items use their current mount for `path`
and keep the same relative `dir`. Internal-volume `dir` stays absolute.
Mount aliases in health.json rebase configured roots and absolute excludes at
read time before DB mount metadata advances, including child settings reads.

If `state.model` is not `ready`, every search uses `legs:["words"]` and a
`degraded` error with code `embedding-unavailable` and the cause "Embedding model
failed verification", including meaning-only requests. Startup deletes the
`<data>/index/code.sqlite` code index (with its `-wal` and `-shm` files) that an
older daemon left behind, verifies both model sizes and digests, checks volume DBs with `PRAGMA quick_check`,
quarantines corrupt stores as `<uuid>.sqlite.bad`, and reconciles online roots
when recovery is needed. health.json records verification, recovery and rebuild
facts for `omafind status --json`.
