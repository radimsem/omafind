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
| `state` | `v:1`, `runtime:"ready"\|"missing"`, `model:"ready"\|"missing"`, `embedder:"stopped"\|"text"\|"full"` | Reply to `hello`. The state shape and pushing a full state whenever a field changes are proposed. |

The scaffold implements the proposed state shape and push-on-change behavior. `runtime` checks for an executable runtime file. `model` checks that both pinned model files exist. `embedder` starts as `stopped`. Presence does not imply verified digests; `build-runtime` verifies them.

```json
{"t":"hello","v":1}
{"t":"state","v":1,"runtime":"missing","model":"missing","embedder":"stopped"}
```

## Search and warm-up (issue #2)

These shapes are proposed. After `hello`, a connection may send:

```json
{"t":"warm"}
{"t":"search","seq":7,"q":"invoice 4412","legs":["words","meaning"],"limit":40}
```

`warm` starts the text-mode embedder and replies with the current `state`, or
`{"t":"warm_failed","reason":"Vulkan device lost"}`.
After `warmMinutes` without a query the embedder stops. Each query resets this
timeout. `warmMinutes:0` stops it immediately after the reply.

The CLI holds an exclusive lock on `~/.local/share/omafind/index.lock` during
reindex. The daemon probes it with a non-blocking shared flock before starting
a server. While reindex holds the lock, all searches use `legs:["words"]` and
`degraded:"indexing in progress"`, including requests for meaning only.
`warm` replies `{"t":"warm_failed","reason":"indexing in progress"}`.
The daemon keeps its shared lock until its server stops. Reindex first tries
the exclusive lock without blocking. If it is busy, reindex prints
`waiting index.lock` once on stderr, holds an exclusive lock on
`~/.local/share/omafind/index.want`, then waits for `index.lock`.
The daemon probes both files without blocking on each 0.5 s tick. When
`index.want` is held, it stops its server and releases the shared lock. Reindex
keeps `index.want` held through server shutdown and the end of the run, so the daemon stays
words-only until indexing ends.
Words-only searches do not wait for server startup or embedding requests.
After the `hello` reply, requests on one connection run concurrently. Search
replies may arrive in any order; clients use `seq` to match them to requests.

A search gets exactly one reply. `seq` is an integer, `q` a string, `legs` a
nonempty array of `words` and/or `meaning`, and `limit` an integer 1..200.
Omitted legs mean both; an omitted limit uses `maxResults` (default 40).
Optional `kinds` is an array of `text`, `pdf`, `image`, `video`, `audio` and/or
`code`. Other types or unknown kinds return `bad-request`. Omission searches
the content index; `code` explicitly includes the code index, using the same
route as `code:`. An empty array matches nothing. Multiple kinds form a union;
a textual prefix narrows it to that kind. Filtering happens before candidate
budgets, the result limit, `total` and `weaker` are computed.
A client may repeat `seq` with words-only then both legs. For one `seq`, a reply
whose `legs` include `meaning` supersedes words-only regardless of arrival order.
Results are flat in score order; grouping is client-side in #4.

```json
{"t":"results","seq":7,"legs":["words","meaning"],"ms":{"embed":14,"scan":9,"words":4,"total":31},"total":17,"weaker":3,"degraded":null,"items":[{"id":"b81e:812:900","kind":"pdf","path":"/home/u/a.pdf","name":"a.pdf","dir":"/home/u","volume":"<uuid>","label":"root","offline":false,"loc":12,"loc_end":null,"open_line":null,"leg":"meaning + words","part":"text","z":3.4,"score":7.4,"weak":false,"hits":["invoice","4412"],"snippet":[{"t":"due on ","m":false},{"t":"invoice","m":true}],"thumb":null,"mtime":1760000000,"size":48211,"info":{}}]}
```

`id` is opaque, resolved only against that connection's latest results.
`offline` is false until #6; `open_line` is null until #3. `loc` is a 1-based
line or PDF page, or seconds for video and audio; images have a null location.
`loc_end` is the next kept frame's second or the audio window's end second.
Extracted HTML/docx/odt set `info.extracted:true`. `part` is `text`, `image`
(an image or rendered PDF page), `name`, `ocr` (an OCR body match), `frame`,
`speech` (a video soundtrack) or `audio`. `z` is null for words-only
results. `weak` means score below half the top score. `total` counts qualified
files before the limit; `weaker` counts weak items in the returned list.
`degraded` is null or a reason string; embedding failures still return words.
Timing fields are milliseconds.

Proposed error replies are `{"t":"error","seq":7,"code":"no-index","reason":"No index exists. Run omafind reindex --root PATH."}` or
`{"t":"error","seq":7,"code":"bad-request","reason":"Invalid search arguments"}`.
An exception while handling a request replies
`{"t":"error","seq":7,"reason":"no such table: meta"}` and leaves the
connection open for the next request. `seq` echoes the request; `code` is
optional for service errors.
The CLI sends seq 1 with both legs and prints the complete results object for
`--json`. It exits 0 for any result, 1 for no index or a service error, 2 for bad arguments, and
3 for a silent socket.

Settings in the plugin's shell.json entry now include `roots` (default `[]`),
`maxResults` (10..200, default 40), `warmMinutes` (0..60, default 5),
`codeRoots` (absolute repository paths, default `[]`), and `imageBudget`
(70, 140 or 280, default 140). Invalid paths are dropped; budgets are not coerced.
`audio` (bool, default true) controls audio files and video soundtracks.
With audio off, audio files have state `skipped` and detail `audio search is off`.
Silent audio has detail `silent audio`. A failed soundtrack leaves frame vectors
in state `partial`, with a failure detail; it is retried on an explicit reindex.
`info.thumb` and `thumb` contain a cached JPEG path in `thumbs/<volume-uuid>/`.
There is no editor setting; openers read the Omarchy default editor.
`shortcut` is a string, default `"SUPER + E"`. It must have one or more uppercase
modifiers (`SUPER`, `SHIFT`, `CTRL`, `ALT`) followed by `+` and an uppercase key
name (letters, digits or underscores). Duplicate modifiers and a modifier used
as the key are invalid. Invalid values fall back to the default.

## Overlay (issue #4)

After `hello`, the plugin may send:

| t | Fields | Behavior |
|---|---|---|
| `preview` | `id`, `q` (string, default `""`) | Render the selected result on demand. Unknown IDs or missing online files reply with `error`, `code:"missing"`, `id` and `reason:"File is missing"`. |
| `open` | `id`, `how:"open"\|"reveal"` (default `"open"`) | Open at the preview jump, or select the file with detached `nautilus --select`. Offline and missing files run nothing. |
| `status` | none | Reply with current indexed-file and queue counts. |

| t | Fields | Behavior |
|---|---|---|
| `preview` | `id`, `mode:"lines"\|"image"\|"bars"`, `lines:[{no,text,hit}]`, `jump`, `range:[first,last]\|null`, `image:path\|null`, `bars:[int]`, `opener`, `editor` (text/code only) | Text/code use a clamped ±8-line window. PDF/video render the selected page/second; images use their thumbnail or source. Audio has 64 RMS bars in 0..100. Unused arrays are empty. Offline items use mode `image` with their cached thumbnail or null. |
| `opened` | `id`, `opener`, `at:string\|null` | Human command label and location: `mpv --start=872`/`14:32`, `omarchy-launch-browser`/`p. 37`, `nvim +212`/`L212`; images and reveals have null `at`. |
| `open_failed` | `id`, `reason:"offline"\|"missing"` | The file cannot be opened; unknown IDs count as missing. |
| `error` | `id`, `for:"open"`, `reason` | Opening raised an unexpected error. A failed preview replies `error` with `id` and no `for`. |
| `status` | `files`, `roots`, `offline:[]`, `done`, `total` | Counts from all index stores, including code. Also pushed when changed, at most once every 0.5 seconds. |

IDs resolve only against that connection's latest `results`; new results clear
its remembered preview jumps. `editor` is the basename of the first command in
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
`offline` stays empty until #6. No text is retained by previews; extracted text
temporaries are deleted after rendering. PDF/video images are cached under
`$XDG_RUNTIME_DIR/omafind/preview/`, keyed by source path, mtime and page/second.
Images are rendered to temporary paths and atomically published. Audio bars
decode at 400 Hz and use a 32-entry memory cache keyed by path and nanosecond
mtime. Status counts run off the event loop and are reused while store and WAL
mtimes stay unchanged; the root count still follows current settings.

```json
{"t":"preview","id":"b81e:812","q":"where they tal"}
{"t":"preview","id":"b81e:812","mode":"lines","lines":[{"no":212,"text":"where they talk","hit":true}],"jump":212,"range":[204,220],"image":null,"bars":[],"opener":"nvim +212","editor":"nvim"}
{"t":"open","id":"b81e:812","how":"open"}
{"t":"opened","id":"b81e:812","opener":"mpv --start=872","at":"14:32"}
{"t":"open_failed","id":"b81e:812","reason":"offline"}
{"t":"status"}
{"t":"status","files":3880,"roots":4,"offline":[],"done":1204,"total":1209}
```

## Setup (issue #5)

| Request t | Reply t | Fields |
|---|---|---|
| `runtime_status`, `runtime_install`, `runtime_pause` | `runtime_progress` | none |
| `discover_start` | `discover_result` | optional `volume` UUID |
| `discover_tree` | `discover_tree` | `root` absolute path or `~/...` |
| `fs_list` | `fs_list` | `path` absolute path or `~`/`~/...` |
| `index_start` | `progress` | none; rereads current settings |

All paths on the wire are absolute, except `excludes` and left-out entry paths, which are POSIX paths relative to their root. Requests may pass `"~"` or `"~/x"`; the daemon expands them and echoes the request string in `root`/`path` and the absolute path in `abs`. Every `counts` object always carries all five keys `text, pdf, image, video, audio` (zeros included). Every request below gets exactly one reply; failures reply `{"t":"error","for":"<request t>","code":"<code>","reason":"<sentence>"}` and never carry `seq` or `id` (Service.qml routes errors on `for` first).

New messages are accepted only after `hello`, like `search`.

```
plugin: {"t":"runtime_status"}
plugin: {"t":"runtime_install"}
plugin: {"t":"runtime_pause"}
daemon: {"t":"runtime_progress","state":"idle|running|paused|failed|done",
         "step":"build|download|null","file":"model|mmproj|null","done":512,"total":865,"unit":"MB",
         "left_seconds":60|null,"reason":null|"<sentence>",
         "build":{"state":"wait|run|ok|failed","seconds":192|null,"tag":"b11461","backend":"Vulkan","gpu":"RTX 3060 12 GB"|null},
         "files":{"model":{"name":"embeddinggemma-2-Q8_0.gguf","state":"wait|run|verify|ok","done":310,"total":310},
                  "mmproj":{"name":"mmproj-embeddinggemma-2-Q8_0.gguf","state":"wait|run|verify|ok","done":202,"total":555}}}
```
- Reply to all three requests is a `runtime_progress` snapshot. While a job runs the daemon also broadcasts it to every ready client, at most twice per second, plus once on every state change.
- MB are decimal and rounded: 309,855,456 B is 310, 554,821,024 B is 555, `total` is `round(sum bytes / 1e6)` = 865. `done` sums both files.
- `state:"done"` means the runtime is built and both digests verified. `files.*.state:"ok"` means sha256 verified (cached by size and mtime, so `runtime_status` hashes at most once per daemon start, in a thread). `build.seconds` is null when the runtime existed before this daemon started.
- `runtime_install` while `running` is a no-op snapshot. While `paused` or `failed` it resumes.

```
plugin: {"t":"discover_start"}                      // $HOME plus every non-system volume
plugin: {"t":"discover_start","volume":"<uuid>"}    // one volume only (#6 new-drive flow)
daemon: {"t":"discover_result", ...body of bin/omafind discover --json}
```
`discover --json` body (A1 produces it, the CLI prints it, the daemon caches and sends it):
```json
{"home":"/home/u","device":"gpu",
 "scan":{"seconds":0.8,"dirs":4812,"volumes":0,"roots":["$HOME"],"scanned_at":1760000000.0},
 "rates":{"gpu":{"text":0.07,"pdf":0.37,"image":0.14,"video":3.2,"audio":1.5,"code":0.042},
          "cpu":{"text":0.13,"pdf":0.54,"image":1.36,"video":18.0,"audio":11.1,"code":0.084},
          "bytes":{"text":11000,"pdf":48000,"image":7000,"video":40000,"audio":12000,"code":10000}},
 "candidates":[{"path":"/home/u/Documents","section":"home","checked":true,"volume":"<uuid>","git":false,
   "dirs":1550,"found":899,"kept":838,
   "found_counts":{"text":806,"pdf":67,"image":26,"video":0,"audio":0},
   "counts":{"text":745,"pdf":67,"image":26,"video":0,"audio":0},
   "exts":[[".md",412],[".pdf",67]],
   "excludes":["vault/exports","archive/old-backups"],
   "left_out":[{"path":"vault/exports","rule":"generated","files":58,"counts":{"text":58,"pdf":0,"image":0,"video":0,"audio":0},
                "evidence":{"pattern":"inv-YYYYMMDD.txt","match":[58,58],"dataset_limit":300}},
               "...no-kind archive/old-backups (0 files), then secrets ** (3 files)"],
   "index_bytes":10000000,"seconds":120}],
 "repos":[{"path":"/home/u/personal/projects/omaone","tracked":1842,"code_files":1700,"rules":["secrets","generated"],
           "index_bytes":17000000,"seconds":71}],
 "not_proposed":{"no_kind":["/home/u/Music"],"dot":212,"heavy":14,"dataset":2}}
```
- `section` is `home` (XDG dir with at least one content file) or `elsewhere`. `checked` is true only for `home`.
- Discovery never has user excludes, so the Documents sample is the board's state before `tax/2024` is left out: kept 838 (745, 67, 26), left out 61 (58 generated, 0 no-kind, 3 secrets). After the user exclude the client ledger gives 793 (731, 45, 17), and the step 2 total goes from 1,254 to 1,209 (MotionSetup `TOT`).
- `excludes` is the pre-applied exclude list for that root (proposed `generated` and `no-kind` paths). `left_out` lists entries in order: excludes in list order, then the `secrets` entry (path `"**"`) last when it has any match. `found - sum(left_out[].files) == kept` always holds.
- `index_bytes` and `seconds` estimate the kept files at `device` rates (section A1.4). `rates` lets the client recompute estimates for any counts.
- `exts`: top extensions of kept content files, descending, at most 3.

```
plugin: {"t":"discover_tree","root":"~/Documents"}
daemon: {"t":"discover_tree","root":"~/Documents","abs":"/home/u/Documents","scanned_at":1760000000.0,
         "candidate":{ ...same shape as a discover_result candidate... },
         "secrets":{"files":3,"counts":{...},"evidence":{"exts":[[".env",3],[".kdbx",1]],"in":["tax/2024","work/clients"]}},
         "dirs":[{"path":"","own":{...},"all_own":2,"sub":{...},"all_sub":905,"dirs":1550,"exts":[[".md",412]],"rule":null,"evidence":null},
                 {"path":"tax/2024","own":{"text":14,"pdf":22,"image":9,"video":0,"audio":0},"all_own":46,
                  "sub":{"text":14,"pdf":22,"image":9,"video":0,"audio":0},"all_sub":46,"dirs":1,
                  "exts":[[".pdf",22],[".md",14],[".png",9]],"rule":null,"evidence":null},
                 {"path":"vault/exports","own":{"text":58,...},"all_own":58,"sub":{...},"all_sub":58,"dirs":1,
                  "exts":[[".txt",58]],"rule":"generated","evidence":{"pattern":"inv-YYYYMMDD.txt","match":[58,58],"dataset_limit":300}},
                 {"path":"archive/old-backups","own":{all zero},"all_own":37,"sub":{all zero},"all_sub":37,"dirs":1,
                  "exts":[],"rule":"no-kind","evidence":{"files":37,"exts":[[".zip",31],[".tar.gz",6]],"searchable":0}}]}
```
- `dirs` holds every directory under the root that holds any non-secret, non-dot file in its subtree, root itself as `""`, sorted by path. `own`/`sub` count content files directly in / under the dir, secrets excluded (secrets live only in `secrets`). `all_own`/`all_sub` count every listed file of any extension (no secrets, no dot paths). `dirs` is the subtree directory count including itself. `exts` for a dir with content: top 3 content extensions in its subtree; for no-kind: `[]` (evidence holds the histogram). `rule` is `generated`, `no-kind` or null (the proposal; user excludes live in the client).
- A root outside the cached scan (a picked folder) is scanned on demand and cached. No cached scan: the daemon runs `discover_start` first.

```
plugin: {"t":"fs_list","path":"~"}
daemon: {"t":"fs_list","path":"~","abs":"/home/u","dirs":["Documents","Pictures"],"error":null}
```
- Sorted case-insensitively, dot dirs and `rules.HEAVY_GLOBS` names left out, at most 500 names. `error` is `"missing"`, `"not-a-directory"` or `"denied"` (with `dirs:[]`) instead of an `error` reply.

```
plugin: {"t":"index_start"}
daemon: {"t":"progress","running":true,"done":612,"queued":597,"volume":"<uuid>","device":"gpu","vram_gb":0.9,
         "kinds":{"text":{"done":734,"total":734},"pdf":{"done":31,"total":49,"pages":412},
                  "image":{"done":51,"total":420,"ocr":63},"video":{"done":0,"total":6},"audio":{"done":0,"total":0}},
         "skipped":{"secrets":4,"size-cap":2},"failed":{"encrypted-pdf":1},
         "problems":[{"path":"/home/u/Documents/a.pdf","reason":"encrypted-pdf"}]}
```
- Reply to `index_start` is a `progress` snapshot. Then the daemon broadcasts `progress` at most twice per second while the index job runs, and once more when it exits (`running:false`). `status` keeps working unchanged for the #4 footer.
- When the child exits non-zero, the final `progress` includes `exit:<code>` (negative for termination by a signal). The daemon then broadcasts exactly one `error` with `for:"index_start"`, `code:"runtime-failed"`, and a `reason` naming the exit code and the absolute `<data>/index/reindex.log` path. These broadcasts report failure after the initial reply; they carry no `seq` or `id`. Successful completion omits `exit` and sends no error.
- `device` is `gpu`, `cpu` or null; `vram_gb` is a float or null (unknown is null, the client hides the token). `skipped` and `failed` omit zero keys. `problems` lists at most 50 failed files.
- `kinds.image.ocr` counts ready images with a non-empty OCR text segment (`kind:"ocr"`); filename and parent-folder text in `name` segments does not count.
- Error codes: `no-roots` (settings have no roots and no codeRoots), `bad-request`, `scan-failed`, `runtime-failed`.

The daemon owns the runtime job: closing a view or disconnecting a client does
not pause it. Build pause terminates the build process group; resume reruns the
idempotent script. Download pause leaves `.part` files for HTTP Range resume.
The daemon refuses to build without a systemd user memory scope.

Indexing runs as a `bin/omafind reindex --incremental` child in a new session.
The daemon holds no index lock and reads committed store counts every 0.5 s.
The child logs to `<data>/index/reindex.log` (0600, replaced for each run), writes
skip counts to `run.json`, and is terminated when the daemon stops. Code stores
are excluded from setup kind counts. `status` retains the issue #4 footer shape.

Later issues append their messages here.
