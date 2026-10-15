# Consistent error handling

Date: 2026-10-15. Branch: `fix/indexing-search-setup-polish`, added to the same pull request as the polish spec.

The owner reset the engine on the live host to run first-time setup again. Step 1 failed with "The runtime build failed: CMAKE_BUILD_TYPE=Release", the model row read "Failed" although no download had started, and the server row read "Starting" before anything was pressed. The real cause was a missing `vulkan-headers` package. Mapping every failure path then showed that the plugin reports errors in five different ways and loses the cause in several places. This spec gives the plugin one error object, one way to show it, and a one-click fix for missing packages.

## Goals

- Every failure a person sees says what happened, why, and what to do next, and offers the fix as a button when there is one.
- A missing package is named exactly and can be installed from the UI through Omarchy's own installer. Setup carries on by itself once the packages are present.
- No cause is thrown away. Build and server output is kept in a log file that the error links to.
- The daemon writes all error copy in one module, and the UI renders it with one component.
- Step 1 says what it will do before it starts, and a failed build no longer marks the model as failed.

## Non-goals

- No change to search ranking, indexing behaviour or the settings shape.
- No new setup step and no change to the step order.
- The `notice` field (`no-code-index`, `code-index-pending`) stays a notice. It reports a state, not a failure.
- No AUR packages. Every package in the fix lists is in the Arch repositories.

## Investigation record

Measured on the live host on 2026-10-15.

| Finding | Detail |
|---|---|
| Build failure | `ggml-vulkan-types.h:5:10: fatal error: vulkan/vulkan_core.h: No such file or directory`. `vulkan-headers` was removed on 2026-10-13 (`pacman -Rns nvidia-sync-debug vulkan-headers`). `shaderc`, `glslang`, `ninja` and `vulkan-icd-loader` are present. System cmake and `spirv-headers` are absent; the script falls back to private copies of both. |
| Lost build output | `install.py` `_build` spawns the script with `stdout=DEVNULL`, keeps the last 20 stderr lines and reports only the last one. Ninja prints compiler errors on stdout, so the reason shown was the script's last stderr line. No log file is written. |
| No build preflight | `tools.check` covers fd, ripgrep, imagemagick, poppler, git, util-linux, ffmpeg and tesseract. It does not check vulkan-headers, shaderc, a C++ compiler or uv. |
| Lost server cause | `embedder.py` sends llama-server stdout and stderr to DEVNULL and replaces "start timed out" or "exited during start" with "Embedding server failed to start". |
| `reason` has four meanings | A sentence (`runtime_progress`, `error`), a code (`open_failed`, `paused`), a bare cause (`warm_failed`) and a per-file detail (`problems`). The same idea also travels as `error` (walks, `fs_list`, children), `degraded` and `exit`. |
| Code from the request name | `SetupService.handle` picks `code` from the request prefix, so a settings error during `index_start` is sent as `runtime-failed`. |
| Other losses | Extractor messages collapse to `extract-failed`. A missing tool shows as per-file `extract-failed`. Code-index failures are skipped in `_progress`. Preview errors are dropped in `SearchView`. The open toast replaces the reason with "error". Daemon import and startup errors go only to the journal. |
| CLI fixes in the UI | Reasons say "Run bin/omafind build-runtime", "omafind reindex --root PATH" or "systemctl --user start omafind" while the person is in the overlay. |
| Five presentations | An elided step 1 hint, an elided setup header subtitle, the wrapping search `Banner` with Retry, a 2.8 s toast, and plain red labels. `setupError` is never shown on step 1. |
| Package picker | Omarchy's Install > Package runs `pacman -Slq \| fzf` with no query option. `omarchy-pkg-add <pkgs>` installs named packages with `--needed`, and Omarchy's own installers run it through `omarchy-launch-floating-terminal-with-presentation`. |

## Design

### The error object

Every failure a person sees carries the same object:

```json
{
  "code": "build-missing-packages",
  "title": "The search engine could not be built.",
  "detail": "Missing build packages: vulkan-headers. Install them, then press Retry.",
  "fix": {"kind": "install", "packages": ["vulkan-headers"]},
  "log": "/home/user/.local/share/omafind/cache/logs/build-runtime.log"
}
```

- `code` is stable kebab-case. The UI branches on it, never on text.
- `title` is one sentence that says what happened.
- `detail` is one or two sentences: why, then what to do next. It names UI controls ("press Retry"), never CLI commands.
- `fix` is optional and has one of two kinds:
  - `{"kind": "install", "packages": [...]}`: the UI offers "Install packages".
  - `{"kind": "retry"}`: the view's own retry control is the fix.
- `log` is optional, an absolute path to a log file. When present the UI offers "Open log".
- The object holds no other fields. Facts that a view shows as tokens (free and needed GB, file counts) stay in the message that carries the object.

### Who writes the copy

`helper/omafindd/errors.py` holds one constructor per code. Each returns a `UserError` (a frozen dataclass with the fields above and `to_dict()`). Callers raise `UserFailure(error)`, an exception that wraps it. Everything that reaches the socket as a failure goes through this module, so the copy rules are applied and tested in one place.

`lib/errors.js` writes copy for two cases only, both where no daemon reply exists:

- `daemon-offline`: the socket does not answer.
- `unknown`: an older daemon sent a bare `reason` string. The UI wraps it as `{code: "unknown", title: reason, detail: ""}`.

It also holds the fix helpers: the pacman command line for an install fix, and the tone for a code.

### Messages that carry it

| Message | Before | After |
|---|---|---|
| `{"t":"error","for":...}` | `code`, `reason` | `for` plus the object's fields at the top level. `seq` and `id` routing is unchanged. |
| `runtime_progress` | `reason` | `error` (object or null) |
| `warm_failed` | `reason` | `error` |
| `results` | `degraded` (string or null) | `degraded` (object or null) |
| `open_failed` | `reason` (code) | `error` |
| `paused` (disk) | `reason: "disk"`, `free_gb`, `need_gb` | `error` with code `disk-low`. `free_gb` and `need_gb` stay. |
| `discover_counts`, `discover_children`, `fs_list` | `error` (string or code) | `error` (object) |
| index exit | `error` broadcast `runtime-failed` | `error` broadcast `index-exited` with `log` |

The daemon stops sending `reason`. The daemon updates together with the plugin (#18), so the only mixed case is a new UI talking to an old daemon during an update, which the `unknown` fallback covers.

### Codes

The copy below is the target. The constructors may adjust wording within the copy rules, and the tests pin the rules, not the exact strings.

| Code | Tone | Title | Detail | Fix | Log |
|---|---|---|---|---|---|
| `tools-missing` | red | Some tools omafind needs are missing. | Missing: fd, ripgrep. Install them, then press Retry. | install | |
| `helper-install-failed` | red | The omafind helper could not be installed. | `<cause>`. Press Retry to try again. | retry | |
| `build-missing-packages` | red | The search engine could not be built. | Missing build packages: `<pkgs>`. Install them, then press Retry. | install | build |
| `build-failed` | red | The search engine could not be built. | `<first error line>`. Open the log for the full output, then press Retry. | retry | build |
| `build-no-scope` | red | The search engine could not be built safely. | The systemd user memory scope is unavailable, so the build would run without a memory cap. Log out and back in, then press Retry. | retry | |
| `model-download-failed` | red | The model could not be downloaded. | `<cause>`. Check the network connection, then press Retry. | retry | |
| `model-verify-failed` | red | The downloaded model is damaged. | `<file>` does not match its checksum. Press Retry to download it again. | retry | |
| `server-start-failed` | red | The embedding server did not start. | `<cause>`. Showing keyword matches until it starts. | retry | server |
| `server-starting` | yellow | The embedding server is starting. | Showing keyword matches until it is ready. | | |
| `embedding-unavailable` | yellow | Search by meaning is unavailable. | `<cause>`. Showing keyword matches. | retry | server |
| `disk-low` | yellow | Indexing is paused. | Free some disk space and indexing resumes by itself. | | |
| `index-exited` | red | Indexing stopped. | The indexer exited with code `<n>`. Open the log for the cause, then press Retry. | retry | reindex |
| `no-roots` | red | No folders are selected. | Pick at least one folder to index. | | |
| `drive-not-mounted` | red | `<drive>` is not connected. | Connect it, then press Retry. | retry | |
| `scan-failed` | red | `<folder>` could not be scanned. | `<cause>`. Press Retry to scan it again. | retry | |
| `binds-failed` | red | Your Hyprland bindings could not be read. | `<cause>`. The shortcut was not saved. | retry | |
| `no-index` | red | Nothing is indexed yet. | Open setup and start the first index. | | |
| `file-missing` | red | `<name>` is missing. | It was moved or deleted after it was indexed. | | |
| `open-failed` | red | `<name>` could not be opened. | `<cause>`. | retry | |
| `tool-missing` | red | `<n>` files need `<tool>`. | They were indexed without `<what>`. Install `<package>` and they are indexed again. | install | |
| `bad-request` | red | omafind sent a request the service did not understand. | `<cause>`. Restart the overlay and try again. | | |
| `internal` | red | Something failed inside the omafind service. | `<cause>`. | retry | |
| `daemon-offline` (UI) | red | The omafind service is not running. | It did not answer on its socket. Press Retry to start it. | retry | start |
| `unknown` (UI) | red | `<reason>` | | | |

`<cause>` is a short, specific clause from the failing call (an HTTP status and message cut to 200 characters, an OS error, the first error line of a log). It never includes a secret.

The `code` follows the cause, not the request that hit it. `SetupService.handle` stops deriving codes from the request prefix. A handler raises `UserFailure` with the right constructor, and anything else becomes `internal`.

### Per-file failures

`progress.problems` items become `{path, code, detail}`, and `progress.failed` keeps counting by `code`. Codes are kebab-case:

`encrypted-pdf`, `timeout`, `extract-failed`, `embedding-failed`, `embedding-precision-fault`, `soundtrack-failed`, `audio-off`, `silent-audio`, `tool-missing`, `code-index-failed`.

- `detail` keeps the extractor's own message ("pdfinfo failed: ...") instead of collapsing it.
- A `FileNotFoundError` for an external tool becomes `tool-missing`, with the tool named in `detail`. `tools.py` maps the tool to its package.
- Code-index failures are counted and listed like any other file. `_progress` stops skipping `code.sqlite`.
- When `tool-missing` files exist, the Index step shows one `tool-missing` card per tool with an install fix. Once the package is present, the UI sends `retry_failed {"code": "tool-missing"}`. The daemon marks those files stale so the running or next pass indexes them again. This is the only new request.

## Capturing the cause

### Build preflight

`tools.py` gains `BUILD_NEEDS`, each entry a check and the package that satisfies it:

| Check | Package |
|---|---|
| `/usr/include/vulkan/vulkan_core.h` exists | `vulkan-headers` |
| `glslc` on `PATH` | `shaderc` |
| `c++` on `PATH` | `gcc` |
| `git` on `PATH` | `git` |
| `uv` on `PATH` | `uv` |

cmake, ninja and spirv-headers stay out on purpose: `build-runtime.sh` falls back to private copies of them.

`tools.check(build=True)` checks these as well as the runtime tools. Three places call it:
- `install.py` before it spawns the build;
- `bin/omafind setup` and `bin/omafind status` when the runtime binary is missing;
- `bin/omafind build-runtime` before it runs the script.

Missing items become `build-missing-packages` (or `tools-missing` for runtime tools), with the exact package list.

### Build log

- The build's stdout and stderr go together to `<data>/cache/logs/build-runtime.log`, which is truncated at the start of each run.
- Progress timing is unchanged.
- On a non-zero exit, `errors.build_failure(log_path)` reads the log and returns the first line that matches `fatal error:`, `error:`, `CMake Error` or `FAILED:`.
- If that line is a missing header listed in `HEADER_PACKAGES` (`vulkan/` → `vulkan-headers`, `spirv/` → `spirv-headers`, `shaderc/` → `shaderc`), the result is `build-missing-packages`. Otherwise it is `build-failed`, with the line as the cause.

### Server log

- llama-server stdout and stderr go to `<data>/cache/logs/llama-server.log`, which is truncated at each start.
- The API key reaches llama-server only through its environment and never through argv, so the log cannot contain it. A test asserts this.
- A start failure keeps its cause: "it did not answer within 60 s" or "it exited with code N", followed by the log's last line that matches `error`, `failed` or `no devices`.
- When the GPU attempt fails and the CPU attempt runs, the log holds the CPU attempt and the cause names both.

### Startup log

A fatal daemon startup error (an import failure, a socket bind failure) is also written to `<data>/cache/logs/omafindd-start.log`. The UI's `daemon-offline` card offers "Open log" when that file exists.

### Helper install from the UI

`bin/omafind setup --json` prints `{"ok": true}` or `{"ok": false, "error": {...}}` on stdout as its last line. `Service.qml` runs it with `--json` and passes the object to step 1 instead of the raw stderr text.

## Showing it

### ErrorCard

`ui/ErrorCard.qml` has the anatomy of the existing `.ban` Banner: a glyph, a bold title, the detail, and buttons on the right.

- **Tone.** Red uses `Color.urgent` with a 0.08 wash for failures. Yellow uses `Palette.yellow` with a 0.08 wash for degraded and paused states. `lib/errors.js` maps code to tone.
- **Detail.** It wraps and is capped at three lines. A longer detail ends with an ellipsis, and "Open log" stays available when there is a log.
- **Install fix.**
  - An "Install packages" button runs `omarchy-launch-floating-terminal-with-presentation omarchy-pkg-add <pkgs>` through `Quickshell.execDetached`.
  - Under the detail, the card shows `sudo pacman -S --needed <pkgs>` in the mono face, with a "Copy" button (`wl-copy`).
  - After a click the card reads "Installing in the terminal" and runs `omarchy-pkg-present <pkgs>` every 2 s. When it succeeds, the card emits `retry` and the view retries.
  - After 10 minutes without success the card returns to its normal state.
- **Retry fix.** The card emits `retry` only when the view sets `retryHere: true`. Views with their own primary control (the setup footer) keep `retryHere: false` and label that control "Retry".
- **Log.** "Open log" runs `omarchy-launch-editor <log>`.
- `Banner.qml` becomes a thin wrapper around `ErrorCard` for the fact-token form (the disk banner), so both share one look.

### Where it appears

| View | Before | After |
|---|---|---|
| Setup 1, Engine | Elided footer hint. `setupError` not shown. | `ErrorCard` under the task rows for install, build, download and server errors. |
| Setup 2, Folders | Red label | `ErrorCard` |
| Setup 3, Index | Header subtitle with the log path cut off | `ErrorCard` in the body for `index-exited`. One `tool-missing` card per tool. |
| Setup 3, problems list | `reason path` | `code`, `detail`, `path` |
| Drive dialog | Red label | `ErrorCard` |
| Search | Yellow `Banner`, "X (X)" text | `ErrorCard` in the banner slot, `retryHere: true` |
| Open fails | 2.8 s toast, reason "error" | Toast with title and detail. A toast whose error has a fix stays until dismissed and shows the fix button. |
| Preview fails | Dropped | Small `ErrorCard` in the preview pane |

`Service.qml` keeps one error property per surface (`engineError`, `folderError`, `indexError`, `driveError`, `searchError`), each an object or null. The catch-all `setupError` string goes away, so an old error from one step can no longer show up on another.

### Step 1 labels

| Situation | Embedding server | Model | File lines | Footer | Button |
|---|---|---|---|---|---|
| Nothing pressed | Not installed | Not downloaded | `310 MB · not downloaded` | Install builds the server (about 3 min) and downloads the model (865 MB). | Install |
| Building | Building · `1m 12s` | Waiting | `queued` | You can close this. Installing keeps going. | Pause |
| Downloading | Built in `3m 05s` | `got` / `left` | progress | same | Pause |
| Build failed | Failed | Not downloaded | `not downloaded` | `ErrorCard` | Retry |
| Download failed | Built or Installed | Failed | as now | `ErrorCard` | Retry |
| Paused | Paused | Paused | as now | as now | Resume |
| Done | Installed | Installed | as now | Everything is installed. Folders are next. | Next: pick folders |

The model sizes and the build time in the hint come from `models.FILES` and a constant. They are not hard-coded in QML.

## Testing

Python (`tests/helper`):
- Every `errors.py` constructor, called with sample arguments, returns:
  - a title and a detail that each end with a full stop;
  - no em or en dash, no "!", none of the banned words;
  - no `bin/omafind`, `systemctl` or `journalctl` in the copy.
- The build-log parser handles:
  - the real failing log trimmed to its relevant part (`vulkan_core.h` → `build-missing-packages` with `vulkan-headers`);
  - a CMake Error fixture and a ninja `FAILED:` fixture (→ `build-failed`);
  - an empty log (→ `build-failed`, "exit N").
- `tools.check(build=True)` with a temporary root and a fake `PATH` reports exactly the missing packages.
- `install.py` writes the log, and a failing fake build script ends in `runtime_progress.error` with the right code and `log`.
- The server start writes the log. It never contains the API key: the test starts a fake server that prints its environment. The cause names a timeout and an exit.
- A missing extractor binary becomes `tool-missing`. Code-index failures appear in `problems`.
- `retry_failed` marks only files whose last failure is that code.
- `SetupService.handle` takes `code` from the cause, and an unexpected exception becomes `internal`.
- `bin/omafind setup --json` prints the object on failure.

JS (`tests/js`):
- `lib/errors.js` wraps a bare `reason`, maps codes to tones, and builds the pacman line.
- `setup.js` returns the step 1 table above for each situation.

QML: `scripts/qmllint.sh`, and a fake-home harness check (objectNames, no key injection) that the card renders each tone, and that the Install and Open log buttons call the expected commands. The commands are stubbed on `PATH`.

All four checks and `git diff --check` pass before each commit.

### End-to-end on the live host

`vulkan-headers` is still missing and the runtime is reset, so the host reproduces the original failure:

1. The owner restarts the daemon on the new code.
2. Setup step 1 → Install → the `build-missing-packages` card names `vulkan-headers`.
3. Install packages → sudo in Omarchy's floating terminal → the card sees the package and retries.
4. The build passes, the model downloads and verifies, and the server starts.
5. Folders and Index complete. `bin/omafind status` reports the runtime, model and index as ready.

## Docs

- `docs/ipc.md`:
  - an "Errors" section with the object, the codes table and the fix kinds;
  - every message row that carried `reason` updated;
  - `retry_failed` added.
- `docs/DESIGN.md`: an `ErrorCard` row in the components table with its two tones, and the setup button labels for step 1 (Install, Pause, Retry, Resume).
- README: a troubleshooting table listing the three log paths and what `build-missing-packages` means.

## Rollout

The work is about six signed, subject-only commits on `fix/indexing-search-setup-polish`. Each commit carries its tests:

1. The error module and the IPC shape, with the daemon messages migrated.
2. The build preflight and the build log.
3. The server log and the start cause.
4. Per-file codes, `tool-missing` and `retry_failed`.
5. `ErrorCard`, `lib/errors.js`, the step 1 labels and the views.
6. Docs.

## Risks

- **Old UI, new daemon.** The plugin and the daemon ship together, and #18 restarts the daemon on update. An old overlay that is still open sees `error` objects where it expects `reason` strings, and shows nothing until it reloads. That is acceptable for one update.
- **`omarchy-pkg-present` polling.** It runs `pacman -Q` every 2 s for at most 10 minutes, which is light. The card stops polling when it is destroyed.
- **Header-to-package map.** It only covers headers the build is known to need. Any other missing header falls back to `build-failed` with the exact line and the log, which is still actionable.
