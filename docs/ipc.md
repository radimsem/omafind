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

Later issues append their messages here.
