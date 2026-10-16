# Consistent error handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every failure omafind shows says what happened, why and what to do next, through one error object from the daemon and one `ErrorCard` in the UI, and a missing package can be installed from the card with Omarchy's own installer.

**Architecture:**
- `helper/omafindd/errors.py` is the only place error copy is written. Every daemon message that reports a failure carries its `UserError.to_dict()` object, and per-file failures carry stable codes.
- The build and llama-server write their output to `cache/logs/`, and a preflight names missing build packages before anything compiles.
- `lib/errors.js` normalises what arrives, including bare `reason` strings from an older daemon. `ui/ErrorCard.qml` renders it with its fix buttons in every view.

**Tech Stack:** Python 3.12 (asyncio, pytest, ruff), QML on Quickshell (Omarchy shell), plain JS libraries tested with `node --test`, bash (`scripts/build-runtime.sh`).

**Spec:** `docs/superpowers/specs/2026-10-15-consistent-error-handling-design.md`

## Global Constraints

- **Branch.** Work on `fix/indexing-search-setup-polish` in the worktree `~/personal/projects/omafind-wt/indexing-search-setup-polish`. Never commit on main.
- **Commits.**
  - Subject only, Conventional Commits, at most 72 characters, one `-m`, no body, no trailers.
  - Sign every commit: `git commit -S -m "<subject>"` (key `01B91D1C3DA525DF`).
  - Stage exact paths. Never stage `.superpowers/` or `.pytest_cache`.
  - Never `push --force`, `reset --hard`, `clean` or `branch -D`. Push or open a PR only when the owner asks.
- **Copy.** All UI and CLI copy uses sentence case and straight quotes. It has no em or en dash in prose and no "!". It avoids the banned words: seamless, leverage, robust, comprehensive, delve, showcase, vibrant, crucial, pivotal, streamline, empower, foster, testament, landscape, tapestry, journey, unlock, elevate. An error says what happened, why, then what to do next. Status lines are fact tokens, not prose.
- **Where copy lives.**
  - The daemon writes error text only in `helper/omafindd/errors.py`.
  - The UI writes error text only for `daemon-offline`, `unknown`, `update-running` and `update-failed`.
  - Fixes name UI controls ("press Retry"), never `bin/omafind`, `systemctl` or `journalctl`.
- **Error shape.** `{code, title, detail, fix?, log?}`. `fix` is `{"kind":"install","packages":[...]}` or `{"kind":"retry"}`. "Open log" appears whenever `log` is set.
- **Install command.** `omarchy-launch-floating-terminal-with-presentation omarchy-pkg-add <pkgs>`. The copyable line is `sudo pacman -S --needed <pkgs>`, and the presence check is `omarchy-pkg-present <pkgs>`, run every 2000 ms for at most 600000 ms.
- **Logs.** `<data>/cache/logs/build-runtime.log`, `llama-server.log` and `omafindd-start.log`, truncated per run. The API key never reaches argv or a log written by omafind.
- **Docs.** `docs/ipc.md` owns the socket messages. Any message change lands in it within this plan (Task 8).
- **Host safety (AGENTS.md).**
  - Never run a runtime build, a llama-server or torch from a task.
  - Unit tests are light and need no memory cap.
  - Never drive the live overlay with key injection, and never switch the live Hyprland submap.
  - Do not edit `~/.config/omarchy/shell.json` by hand.
- **Live daemon.** The live plugin is linked to this worktree. Between Task 2 and Task 7 the UI reads old fields, so the owner must not restart the live daemon or shell until Task 7 is committed.
- **Checks before every commit:**
  ```
  uv run --project helper pytest -q
  node --test "tests/js/*.test.mjs"
  uv run --project helper ruff check helper tests bin/omafind scripts evals
  scripts/qmllint.sh
  git diff --check
  ```

## Review Focus

1. **The person closes the install terminal or the sudo prompt fails.** `omarchy-pkg-present` never succeeds. The card must stay usable: "Install packages" can be pressed again and "Retry" works while polling, and polling stops on retry, on a new error code or when the card is destroyed. The card does not sit in "Installing in the terminal" for 10 minutes with no way out. Task 6 covers this in the harness step and in the ErrorCard state logic.
2. **The logs folder cannot be written** (read-only cache, full disk). The build and the server still start. Their error carries no `log`, and nothing raises out of `_run` or the embedder. Task 4 covers the server. Task 3 gets a test where opening the build log fails and the build still runs and reports `build-failed` without a log.
3. **Two build packages are missing and the person installs only one.** Auto-retry fires only when all are present. If Retry is pressed early, the preflight runs again and names only the one still missing. This is a Task 3 test: the preflight with one of two present.
4. **A new plugin talks to an old daemon** during an update. Every surface still shows text through `Errors.from` and `Errors.wrap` (bare `reason`, string `degraded`, string walk errors), never `[object Object]` or a blank. Tasks 6 and 7 cover this in their JS tests.
5. **A stale error from another step.** Starting an action clears the error on its own surface: `runEngine` clears `engineError`, `startIndexing` clears `indexError`, a new discovery clears `folderError`. An error from step 1 never shows on step 3. Task 6 covers this in the Service routing tests or the harness check.

---

### Task 1: The error module

**Files:**
- Create: `helper/omafindd/errors.py`
- Create: `tests/helper/test_errors.py`
- Create: `tests/fixtures/build/missing-header.log`, `tests/fixtures/build/cmake-error.log`, `tests/fixtures/build/ninja-only.log`

**Interfaces:**
- Consumes: nothing.
- Produces, used by every later task:
  - `errors.UserError(code, title, detail="", fix=None, log=None)` with `.to_dict() -> dict`.
  - `errors.UserFailure(error: UserError)`, an exception with `.error`.
  - `errors.RETRY`, `errors.install(packages) -> dict`, `errors.cause(text, limit=200) -> str`, `errors.reply(kind: str, error: UserError) -> dict`.
  - One constructor per code: `tools_missing(packages)`, `helper_install_failed(reason)`, `build_missing_packages(packages, log=None)`, `build_failed(reason, log=None)`, `build_no_scope()`, `model_download_failed(reason)`, `model_verify_failed(name)`, `server_start_failed(reason, log=None)`, `server_starting()`, `embedding_unavailable(reason, log=None)`, `disk_low()`, `index_exited(code, log=None)`, `no_roots()`, `drive_not_mounted(drive)`, `scan_failed(folder, reason)`, `binds_failed(reason)`, `no_index()`, `file_missing(name)`, `open_failed(name, reason)`, `tool_missing(count, tool, what, package)`, `bad_request(reason)`, `internal(reason)`.
  - `errors.HEADER_PACKAGES` and `errors.build_failure(log_path, exit_code) -> UserError`.

- [ ] **Step 1: Write the build-log fixtures**

`tests/fixtures/build/missing-header.log` holds the trimmed live failure from 2026-10-15:

```
[212/298] Building CXX object ggml/src/ggml-vulkan/CMakeFiles/ggml-vulkan.dir/ggml-vulkan.cpp.o
FAILED: ggml/src/ggml-vulkan/CMakeFiles/ggml-vulkan.dir/ggml-vulkan.cpp.o
In file included from /home/u/.local/share/omafind/cache/llama.cpp/ggml/src/ggml-vulkan/ggml-vulkan.cpp:1:
/home/u/.local/share/omafind/cache/llama.cpp/ggml/src/ggml-vulkan/ggml-vulkan-types.h:5:10: fatal error: vulkan/vulkan_core.h: No such file or directory
compilation terminated.
ninja: build stopped: subcommand failed.
```

`tests/fixtures/build/cmake-error.log`:

```
-- The C compiler identification is GNU 15.2.1
CMake Error at ggml/src/ggml-vulkan/CMakeLists.txt:4 (find_package):
  Could not find a package configuration file provided by "Vulkan".
-- Configuring incomplete, errors occurred!
```

`tests/fixtures/build/ninja-only.log`:

```
[3/298] Generating shaders
FAILED: ggml/src/ggml-vulkan/ggml-vulkan-shaders.hpp
ninja: build stopped: subcommand failed.
```

- [ ] **Step 2: Write the failing tests**

`tests/helper/test_errors.py`:

```python
import re
from pathlib import Path

import pytest
from omafindd import errors

FIXTURES = Path(__file__).parent.parent / "fixtures" / "build"

SAMPLES = {
    "tools_missing": (["fd", "ripgrep"],),
    "helper_install_failed": ("uv: command not found",),
    "build_missing_packages": (["vulkan-headers"], "/tmp/build.log"),
    "build_failed": ("CMake Error at CMakeLists.txt:4", "/tmp/build.log"),
    "build_no_scope": (),
    "model_download_failed": ("HTTP 503: Service Unavailable",),
    "model_verify_failed": ("embeddinggemma-2.gguf",),
    "server_start_failed": ("It exited with code 1", "/tmp/llama-server.log"),
    "server_starting": (),
    "embedding_unavailable": ("embedding model failed verification",),
    "disk_low": (),
    "index_exited": (3, "/tmp/reindex.log"),
    "no_roots": (),
    "drive_not_mounted": ("Photos2024",),
    "scan_failed": ("~/Pictures", "Permission denied"),
    "binds_failed": ("hyprctl exited with code 1",),
    "no_index": (),
    "file_missing": ("notes.md",),
    "open_failed": ("notes.md", "omarchy-launch-editor exited with code 1"),
    "tool_missing": (12, "tesseract", "text recognition", "tesseract"),
    "bad_request": ("Pick an absolute folder path",),
    "internal": ("KeyError: 'roots'",),
}

BANNED = (
    "seamless",
    "leverage",
    "robust",
    "comprehensive",
    "delve",
    "showcase",
    "vibrant",
    "crucial",
    "pivotal",
    "streamline",
    "empower",
    "foster",
    "testament",
    "landscape",
    "tapestry",
    "journey",
    "unlock",
    "elevate",
    "oops",
    "let's",
)


def constructors():
    return sorted(
        name
        for name, value in vars(errors).items()
        if callable(value)
        and not name.startswith("_")
        and name
        not in {
            "UserError",
            "UserFailure",
            "install",
            "cause",
            "reply",
            "build_failure",
            "dataclass",
            "Path",
        }
    )


def test_every_constructor_has_a_sample():
    assert constructors() == sorted(SAMPLES)


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_copy_follows_the_rules(name):
    error = getattr(errors, name)(*SAMPLES[name])
    assert re.fullmatch(r"[a-z]+(-[a-z]+)*", error.code)
    for text in (error.title, error.detail):
        assert text.endswith("."), text
        assert "—" not in text and "–" not in text
        assert "!" not in text
        for word in BANNED:
            assert word not in text.lower(), (word, text)
        for command in ("bin/omafind", "systemctl", "journalctl"):
            assert command not in text
    # A title may open with the file, folder or count it names; otherwise it starts with a capital.
    args = SAMPLES[name]
    if not (args and error.title.startswith(str(args[0]))):
        assert error.title[:1].isupper() or error.title.startswith("omafind"), error.title


def test_to_dict_omits_missing_fix_and_log():
    assert errors.no_roots().to_dict() == {
        "code": "no-roots",
        "title": "No folders are selected.",
        "detail": "Pick at least one folder to index.",
    }
    body = errors.build_missing_packages(
        ["vulkan-headers", "shaderc", "vulkan-headers"], "/x.log"
    ).to_dict()
    assert body["fix"] == {"kind": "install", "packages": ["vulkan-headers", "shaderc"]}
    assert body["log"] == "/x.log"
    assert (
        body["detail"]
        == "Missing build packages: vulkan-headers, shaderc. Install them, then press Retry."
    )


def test_reply_routes_by_request():
    assert errors.reply("binds_get", errors.binds_failed("boom")) == {
        "t": "error",
        "for": "binds_get",
        "code": "binds-failed",
        "title": "Your Hyprland bindings could not be read.",
        "detail": "Boom. The shortcut was not saved.",
        "fix": {"kind": "retry"},
    }


def test_user_failure_carries_the_error():
    failure = errors.UserFailure(errors.no_index())
    assert failure.error.code == "no-index"
    assert str(failure) == "Nothing is indexed yet."


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("connection refused\nmore", "Connection refused"),
        ("ggml-vulkan.h:5:10: fatal error: x", "ggml-vulkan.h:5:10: fatal error: x"),
        ("HTTP 500: too large.", "HTTP 500: too large"),
        ("", "No reason was given"),
        ("x" * 300, "X" + "x" * 198 + "\u2026"),
    ],
)
def test_cause_is_one_short_clause(text, expected):
    assert errors.cause(text) == expected


def test_tool_missing_counts_files():
    assert (
        errors.tool_missing(1, "tesseract", "text recognition", "tesseract").title
        == "1 file needs tesseract."
    )
    assert (
        errors.tool_missing(1200, "ffmpeg", "video frames", "ffmpeg").title
        == "1,200 files need ffmpeg."
    )


def test_missing_vulkan_header_names_the_package():
    error = errors.build_failure(FIXTURES / "missing-header.log", 1)
    assert error.code == "build-missing-packages"
    assert error.fix == {"kind": "install", "packages": ["vulkan-headers"]}
    assert error.log == str(FIXTURES / "missing-header.log")


def test_cmake_error_is_a_build_failure_with_its_line():
    error = errors.build_failure(FIXTURES / "cmake-error.log", 1)
    assert error.code == "build-failed"
    assert error.detail.startswith(
        "CMake Error at ggml/src/ggml-vulkan/CMakeLists.txt:4 (find_package). Open the log"
    )


def test_ninja_failure_without_a_compiler_line_uses_failed():
    error = errors.build_failure(FIXTURES / "ninja-only.log", 1)
    assert error.code == "build-failed"
    assert error.detail.startswith("FAILED: ggml/src/ggml-vulkan/ggml-vulkan-shaders.hpp")


def test_empty_or_missing_log_reports_the_exit_code(tmp_path):
    empty = tmp_path / "build.log"
    empty.write_text("")
    assert errors.build_failure(empty, 2).detail.startswith("The build exited with code 2.")
    assert errors.build_failure(tmp_path / "absent.log", 2).code == "build-failed"
```


- [ ] **Step 3: Run the tests to see them fail**

Run: `uv run --project helper pytest -q tests/helper/test_errors.py`
Expected: collection error `ImportError: cannot import name 'errors' from 'omafindd'`.

- [ ] **Step 4: Write `helper/omafindd/errors.py`**

```python
"""Every failure a person sees, written once. docs/ipc.md "Errors" documents the shape."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

RETRY = {"kind": "retry"}

# Headers the runtime build includes, mapped to the Arch package that ships them.
HEADER_PACKAGES = {"vulkan/": "vulkan-headers", "spirv/": "spirv-headers", "shaderc/": "shaderc"}

# Ninja prints `FAILED:` before the compiler's line, so the most specific line wins.
_BUILD_LINES = (
    re.compile(r"fatal error:"),
    re.compile(r"\berror:|CMake Error"),
    re.compile(r"^FAILED:"),
)
_MISSING_HEADER = re.compile(r"fatal error: ([\w./+-]+): No such file or directory")


@dataclass(frozen=True)
class UserError:
    code: str
    title: str
    detail: str = ""
    fix: dict | None = None
    log: str | None = None

    def to_dict(self) -> dict:
        body = {"code": self.code, "title": self.title, "detail": self.detail}
        if self.fix is not None:
            body["fix"] = self.fix
        if self.log is not None:
            body["log"] = self.log
        return body


class UserFailure(Exception):
    """Raised by handlers so the socket layer sends this error instead of `internal`."""

    def __init__(self, error: UserError):
        super().__init__(error.title)
        self.error = error


def install(packages) -> dict:
    return {"kind": "install", "packages": list(dict.fromkeys(packages))}


def reply(kind: str, error: UserError) -> dict:
    return {"t": "error", "for": kind, **error.to_dict()}


def cause(text, limit: int = 200) -> str:
    """The first non-empty line of `text`, without a final period, at most `limit` characters."""
    line = next((part.strip() for part in str(text).splitlines() if part.strip()), "")
    line = line.rstrip(".")
    if len(line) > limit:
        line = line[: limit - 1].rstrip() + "…"
    if not line:
        return "No reason was given"
    # Capitalise a plain word ("connection refused"), never a path ("ggml-vulkan.h:5").
    return line[:1].upper() + line[1:] if re.match(r"[a-z]+(?![\w./:-])", line) else line


def _log(path) -> str | None:
    return None if path is None else str(path)


def tools_missing(packages) -> UserError:
    names = ", ".join(dict.fromkeys(packages))
    return UserError(
        "tools-missing",
        "Some tools omafind needs are missing.",
        f"Missing: {names}. Install them, then press Retry.",
        install(packages),
    )


def helper_install_failed(reason) -> UserError:
    return UserError(
        "helper-install-failed",
        "The omafind helper could not be installed.",
        f"{cause(reason)}. Press Retry to try again.",
        RETRY,
    )


def build_missing_packages(packages, log=None) -> UserError:
    names = ", ".join(dict.fromkeys(packages))
    return UserError(
        "build-missing-packages",
        "The search engine could not be built.",
        f"Missing build packages: {names}. Install them, then press Retry.",
        install(packages),
        _log(log),
    )


def build_failed(reason, log=None) -> UserError:
    return UserError(
        "build-failed",
        "The search engine could not be built.",
        f"{cause(reason)}. Open the log for the full output, then press Retry.",
        RETRY,
        _log(log),
    )


def build_no_scope() -> UserError:
    return UserError(
        "build-no-scope",
        "The search engine could not be built safely.",
        "The systemd user memory scope is unavailable, so the build would run without a "
        "memory cap. Log out and back in, then press Retry.",
        RETRY,
    )


def model_download_failed(reason) -> UserError:
    return UserError(
        "model-download-failed",
        "The model could not be downloaded.",
        f"{cause(reason)}. Check the network connection, then press Retry.",
        RETRY,
    )


def model_verify_failed(name) -> UserError:
    return UserError(
        "model-verify-failed",
        "The downloaded model is damaged.",
        f"{name} does not match its checksum. Press Retry to download it again.",
        RETRY,
    )


def server_start_failed(reason, log=None) -> UserError:
    return UserError(
        "server-start-failed",
        "The embedding server did not start.",
        f"{cause(reason)}. Showing keyword matches until it starts.",
        RETRY,
        _log(log),
    )


def server_starting() -> UserError:
    return UserError(
        "server-starting",
        "The embedding server is starting.",
        "Showing keyword matches until it is ready.",
    )


def embedding_unavailable(reason, log=None) -> UserError:
    return UserError(
        "embedding-unavailable",
        "Search by meaning is unavailable.",
        f"{cause(reason)}. Showing keyword matches.",
        RETRY,
        _log(log),
    )


def disk_low() -> UserError:
    return UserError(
        "disk-low", "Indexing is paused.", "Free some disk space and indexing resumes by itself."
    )


def index_exited(code: int, log=None) -> UserError:
    return UserError(
        "index-exited",
        "Indexing stopped.",
        f"The indexer exited with code {code}. Open the log for the cause, then press Retry.",
        RETRY,
        _log(log),
    )


def no_roots() -> UserError:
    return UserError("no-roots", "No folders are selected.", "Pick at least one folder to index.")


def drive_not_mounted(drive) -> UserError:
    return UserError(
        "drive-not-mounted", f"{drive} is not connected.", "Connect it, then press Retry.", RETRY
    )


def scan_failed(folder, reason) -> UserError:
    return UserError(
        "scan-failed",
        f"{folder} could not be scanned.",
        f"{cause(reason)}. Press Retry to scan it again.",
        RETRY,
    )


def binds_failed(reason) -> UserError:
    return UserError(
        "binds-failed",
        "Your Hyprland bindings could not be read.",
        f"{cause(reason)}. The shortcut was not saved.",
        RETRY,
    )


def no_index() -> UserError:
    return UserError("no-index", "Nothing is indexed yet.", "Open setup and start the first index.")


def file_missing(name) -> UserError:
    return UserError(
        "file-missing", f"{name} is missing.", "It was moved or deleted after it was indexed."
    )


def open_failed(name, reason) -> UserError:
    return UserError("open-failed", f"{name} could not be opened.", f"{cause(reason)}.", RETRY)


def tool_missing(count: int, tool: str, what: str, package: str) -> UserError:
    files = "1 file needs" if count == 1 else f"{count:,} files need"
    return UserError(
        "tool-missing",
        f"{files} {tool}.",
        f"They were indexed without {what}. Install {package} and they are indexed again.",
        install([package]),
    )


def bad_request(reason) -> UserError:
    return UserError(
        "bad-request",
        "omafind sent a request the service did not understand.",
        f"{cause(reason)}. Restart the overlay and try again.",
    )


def internal(reason) -> UserError:
    return UserError(
        "internal", "Something failed inside the omafind service.", f"{cause(reason)}.", RETRY
    )


def build_failure(log_path, exit_code: int) -> UserError:
    """Classify a failed runtime build from its combined stdout and stderr log."""
    try:
        lines = [line.strip() for line in Path(log_path).read_text(errors="replace").splitlines()]
    except OSError:
        lines = []
    line = next((line for pattern in _BUILD_LINES for line in lines if pattern.search(line)), None)
    if line is None:
        return build_failed(f"The build exited with code {exit_code}", log_path)
    missing = _MISSING_HEADER.search(line)
    if missing:
        package = next(
            (pkg for prefix, pkg in HEADER_PACKAGES.items() if missing[1].startswith(prefix)), None
        )
        if package:
            return build_missing_packages([package], log_path)
    # CMake ends its line with "(message):", which would read badly before the next sentence.
    return build_failed(line.rstrip(":"), log_path)
```


- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run --project helper pytest -q tests/helper/test_errors.py`
Expected: all pass.

- [ ] **Step 6: Run the full checks**

```
uv run --project helper pytest -q
node --test "tests/js/*.test.mjs"
uv run --project helper ruff check helper tests bin/omafind scripts evals
scripts/qmllint.sh
git diff --check
```

Expected: all green. Nothing imports `errors` yet, so the other suites are unchanged.

- [ ] **Step 7: Commit**

```bash
git add helper/omafindd/errors.py tests/helper/test_errors.py tests/fixtures/build/missing-header.log tests/fixtures/build/cmake-error.log tests/fixtures/build/ninja-only.log
git commit -S -m "feat(omafindd): add one error object for every user-facing failure"
```

---

### Task 2: Daemon messages carry the object

> Until Task 7 lands, the UI shows blank or stale error fields, so do not restart the live daemon from this branch before then.

**Files:**
- Modify: `helper/omafindd/errors.py` (Task 1 file: add `index_running()` after `disk_low()`)
- Modify: `helper/omafindd/embedder.py:41-42` (`EmbeddingError` gains `user_error`; this task owns it, Task 4 only sets it)
- Modify: `helper/omafindd/setup.py:13` (import), `:92-195` (`_error` removed, `handle`), `:197-207` (`_binds`), `:243-272` (`_count_walk`), `:322-330` (`_start_index` no-roots), `:513-523` (`poll` index exit)
- Modify: `helper/omafindd/service.py:7` (import), `:15-17` (new `_unavailable` after `volume_for`), `:97-113` (`_start`), `:202-230` (`_warm`, `_start_query`), `:313-382` (`_handle`)
- Modify: `helper/omafindd/search.py:10` (import), `:260-271` (`Searcher._query`)
- Modify: `helper/omafindd/ipc.py:14` (import), `:27-28` (new `_failure`, `_name`), `:167-224` (`dispatch`), `:229-280` (`_overlay`)
- Modify: `helper/omafindd/diskguard.py:1-2`, `:26`
- Modify: `helper/omafindd/discovery.py:9` (import), `:113-131` (`top`, plus new `_scanned` and `_label` above it), `:270-272` (`Walk.run`), `:297-300` (`children`), `:373-378` (`list_dirs`)
- Modify: `helper/omafindd/install.py:11`, `:60`, `:136`, `:153`, `:178-182` (no scope), `:217-223` (build exit), `:265-287` (`_run`)
- Modify: `bin/omafind:337-339` (search error print), `:416-421` (discover catches `UserFailure`)
- `rules.py` needs no change: `rules.walk` raises `OSError("fd failed: ...")`, and that text becomes the `scan-failed` cause in `Walk.run`.
- Test: `tests/helper/test_errors.py`, `test_embedder.py`, `test_discovery.py`, `test_diskguard.py`, `test_ipc_setup.py`, `test_ipc_search.py`, `test_ipc_overlay.py`, `test_ipc_volumes.py`, `test_permissions.py`, `test_install.py`, `test_cli.py`

**Interfaces:**
- Consumes (Task 1, `helper/omafindd/errors.py`): `UserError`, `UserFailure`, `reply(kind, error)`, `bad_request`, `internal`, `no_roots`, `index_exited`, `drive_not_mounted`, `scan_failed`, `binds_failed`, `no_index`, `file_missing`, `open_failed`, `disk_low`, `server_starting`, `embedding_unavailable`, `server_start_failed` (test only), `build_no_scope`, `build_failed`, `model_download_failed`, `model_verify_failed`.
- Produces:
  - `errors.index_running() -> UserError` (code `index-running`, yellow tone in `lib/errors.js`).
  - `embedder.EmbeddingError(*args, user_error=None)` with attribute `user_error` (class default `None`). Task 4 raises it with `user_error=errors.server_start_failed(cause, log)`; `service.py` and `search.py` already carry that object to `warm_failed.error` and `results.degraded`.
  - Message shapes exactly as the contract's "Message shapes after Task 2": `{"t":"error","for":kind,**obj}` for every setup request; `{"t":"error","seq":seq,**obj}` for search (`bad-request`, `no-index`, `internal`); `{"t":"error","id":id,**obj}` for preview (`file-missing`, `bad-request`, `internal`); `{"t":"error","id":id,"for":"open",**obj}` for open (`bad-request`, `internal`); `open_failed.error` (`file-missing`, `drive-not-mounted`, `open-failed`); `warm_failed.error`; `results.degraded` (object or null: `index-running`, `server-starting`, `embedding-unavailable`, or whatever `EmbeddingError.user_error` holds, such as Task 4's `server-start-failed`); `paused.error` (`disk-low`, plus `free_gb`, `need_gb`); `runtime_progress.error` (object or null, `reason` gone); `discover_counts.error` (object, key absent on success); `discover_children.error` and `fs_list.error` (object, `null` on success as today; JS treats null and absent the same); index exit broadcast `errors.reply("index_start", errors.index_exited(n, <data>/index/reindex.log))`.
  - No `reason_code` legacy field on `fs_list`: no JS or QML branches on `missing`, `not-a-directory` or `denied` (see the consumers note at the end).
  - `SetupService.handle`: `UserFailure` → its object; any other exception → `internal`. The request name never picks the code.
  - `IpcServer.dispatch` generic exception → `internal` (or the `UserFailure` object) on every route.

The test and code hunks below were applied to a copy of this branch with Task 1's `errors.py` from the contract in place. The suite went from 73 failures (tests applied, old code) to `985 passed` (both applied, after Task 1), and `ruff` passed on every file this task touches.

- [ ] **Step 1: Write the failing tests**

`tests/helper/test_errors.py`: add one line to Task 1's `SAMPLES` dict, next to `disk_low`, in the same `name: args` form Task 1 uses:

```python
    "index_running": (),
```

`tests/helper/test_embedder.py`: append at the end of the file (`EmbeddingError` is already imported at the top):

```diff
diff --git a/tests/helper/test_embedder.py b/tests/helper/test_embedder.py
index 371d336..5d65db8 100644
--- a/tests/helper/test_embedder.py
+++ b/tests/helper/test_embedder.py
@@ -618,3 +618,13 @@ async def test_only_input_errors_reject_the_file(monkeypatch, status, rejected):
         assert isinstance(caught.value, EmbeddingRejected) is rejected
     finally:
         await embedder.stop()
+
+
+def test_embedding_error_carries_an_optional_error_object():
+    from omafindd import errors
+
+    failure = errors.server_starting()
+    error = EmbeddingError("the embedding server is starting", user_error=failure)
+    assert error.user_error is failure
+    assert str(error) == "the embedding server is starting"
+    assert EmbeddingError("Embedding server is not running").user_error is None
```

`tests/helper/test_discovery.py`: listing errors, walk errors, child errors and `top` failures become objects. `top` raises `UserFailure` for an unmounted drive and an unreadable root.

```diff
diff --git a/tests/helper/test_discovery.py b/tests/helper/test_discovery.py
index 4d4d950..c498b77 100644
--- a/tests/helper/test_discovery.py
+++ b/tests/helper/test_discovery.py
@@ -3,7 +3,8 @@ import os
 from pathlib import Path

 import pytest
-from omafindd import discovery
+from omafindd import discovery, errors
+from omafindd.errors import UserFailure


 class Process:
@@ -46,8 +47,10 @@ def test_list_dirs_hides_dot_and_heavy_and_reports_missing(tmp_path):
     (tmp_path / 'file').touch()
     assert discovery.list_dirs('~', home=tmp_path) == {
         'path': '~', 'abs': str(tmp_path), 'dirs': ['apple', 'Zebra'], 'error': None}
-    assert discovery.list_dirs('~/missing', home=tmp_path)['error'] == 'missing'
-    assert discovery.list_dirs('~/file', home=tmp_path)['error'] == 'not-a-directory'
+    assert discovery.list_dirs('~/missing', home=tmp_path)['error'] == errors.scan_failed(
+        str(tmp_path / 'missing'), 'No such file or directory').to_dict()
+    assert discovery.list_dirs('~/file', home=tmp_path)['error'] == errors.scan_failed(
+        str(tmp_path / 'file'), 'Not a directory').to_dict()


 def test_list_dirs_reports_an_unreadable_directory(tmp_path, monkeypatch):
@@ -56,7 +59,8 @@ def test_list_dirs_reports_an_unreadable_directory(tmp_path, monkeypatch):

     monkeypatch.setattr(discovery.os, 'scandir', denied)
     assert discovery.list_dirs('/root', home=tmp_path) == {
-        'path': '/root', 'abs': '/root', 'dirs': [], 'error': 'denied'}
+        'path': '/root', 'abs': '/root', 'dirs': [],
+        'error': errors.scan_failed('/root', 'Permission denied').to_dict()}


 def test_xdg_dirs_reads_home_and_omits_home_itself(tmp_path):
@@ -132,8 +136,25 @@ def test_top_for_a_volume_lists_the_mount(tmp_path):
     assert body["roots"] == [{"path": str(drive), "volume": "usb"}]
     assert [(r["name"], r["volume"], r["xdg"]) for r in body["folders"]] == [
         ("Photos", "usb", False)]
-    with pytest.raises(ValueError):
+    with pytest.raises(UserFailure) as raised:
         discovery.top(home=tmp_path / "home", volume="gone", lsblk=lsblk)
+    assert raised.value.error == errors.drive_not_mounted("The drive")
+
+
+def test_top_for_an_unmounted_volume_names_the_drive(tmp_path):
+    lsblk = {"blockdevices": [{"uuid": "disk", "children": [
+        {"uuid": "usb", "label": "Photos2024", "mountpoints": [None]}]}]}
+    with pytest.raises(UserFailure) as raised:
+        discovery.top(home=tmp_path / "home", volume="usb", lsblk=lsblk)
+    assert raised.value.error == errors.drive_not_mounted("Photos2024")
+
+
+def test_top_of_an_unreadable_home_names_the_folder(tmp_path):
+    with pytest.raises(UserFailure) as raised:
+        discovery.top(home=tmp_path / "gone", lsblk={"blockdevices": []}, xdg={},
+                      volume_of=lambda path: ("root", path))
+    assert raised.value.error == errors.scan_failed(str(tmp_path / "gone"),
+                                                    "No such file or directory")


 def test_top_caps_rows_at_limit(tmp_path, monkeypatch):
@@ -191,7 +212,9 @@ def test_walk_of_a_missing_root_ends_with_error(tmp_path):
     walk = discovery.Walk(tmp_path / "gone")
     batches = []
     walk.run(batches.append)
-    assert batches[-1]["done"] is True and batches[-1]["error"]
+    assert batches[-1]["done"] is True
+    assert batches[-1]["error"] == errors.scan_failed(
+        str(tmp_path / "gone"), "No such file or directory").to_dict()
     assert walk.snapshot()["error"] == batches[-1]["error"]


@@ -223,7 +246,8 @@ def test_children_mark_datasets_with_evidence(tmp_path):
 def test_children_of_unreadable_folder_report_error(tmp_path):
     body = discovery.children(tmp_path / "missing")
     assert body == {"path": str(tmp_path / "missing"), "dirs": [],
-                    "error": "No such file or directory"}
+                    "error": errors.scan_failed(str(tmp_path / "missing"),
+                                                "No such file or directory").to_dict()}


 def test_stop_terminates_and_reaps_the_fd_process(tmp_path):
```

`tests/helper/test_diskguard.py`:

```diff
diff --git a/tests/helper/test_diskguard.py b/tests/helper/test_diskguard.py
index caa0bc5..8511b89 100644
--- a/tests/helper/test_diskguard.py
+++ b/tests/helper/test_diskguard.py
@@ -1,5 +1,7 @@
 from types import SimpleNamespace

+from omafindd import errors
+

 def guard_at(free):
     from omafindd.diskguard import DiskGuard
@@ -10,7 +12,8 @@ def guard_at(free):
 def test_1_9_gb_pauses_with_need_gb_2():
     guard = guard_at(1_900_000_000)
     assert guard.low()
-    assert guard.check() == {'t': 'paused', 'reason': 'disk', 'free_gb': 1.9, 'need_gb': 2}
+    assert guard.check() == {'t': 'paused', 'error': errors.disk_low().to_dict(),
+                             'free_gb': 1.9, 'need_gb': 2}
     assert guard.check() is None


```

`tests/helper/test_ipc_setup.py`: codes follow the cause, unexpected failures are `internal` whatever the request, the index exit carries `index-exited` with the `reindex.log` path, and binds failures keep their cause.

```diff
diff --git a/tests/helper/test_ipc_setup.py b/tests/helper/test_ipc_setup.py
index 065ae4c..9199600 100644
--- a/tests/helper/test_ipc_setup.py
+++ b/tests/helper/test_ipc_setup.py
@@ -5,7 +5,7 @@ from pathlib import Path
 from types import SimpleNamespace

 import pytest
-from omafindd import discovery
+from omafindd import discovery, errors
 from omafindd.ipc import IpcServer
 from omafindd.settings import Settings
 from omafindd.setup import SetupService
@@ -209,15 +209,15 @@ async def test_walk_failure_ends_with_done_and_error(service):
     service.walk = broken
     await service.handle({"t": "discover_start"})
     await asyncio.gather(*service._discovery)
+    failure = errors.scan_failed("/h", "fd failed: boom").to_dict()
     assert service.test_pushes[-1] == {"t": "discover_counts", "root": "/h", "counts": {},
-                                       "done": True, "seconds": None,
-                                       "error": "fd failed: boom"}
+                                       "done": True, "seconds": None, "error": failure}

     service.test_pushes.clear()
     await service.handle({"t": "discover_start"})
     await asyncio.gather(*service._discovery)
     assert service.test_pushes[-1]["done"]
-    assert service.test_pushes[-1]["error"] == "fd failed: boom"
+    assert service.test_pushes[-1]["error"] == failure
     assert attempts == [Path("/h"), Path("/h")]
     assert "/h" not in service._walked

@@ -272,13 +272,14 @@ async def test_fs_list(service):


 async def test_fs_list_missing(service):
+    failure = errors.scan_failed("/missing", "No such file or directory").to_dict()
     service.list_dirs = lambda path, **kw: {
         "path": path,
         "abs": path,
         "dirs": [],
-        "error": "missing",
+        "error": failure,
     }
-    assert (await service.handle({"t": "fs_list", "path": "/missing"}))["error"] == "missing"
+    assert (await service.handle({"t": "fs_list", "path": "/missing"}))["error"] == failure


 async def test_index_start_spawns_once(service):
@@ -294,12 +295,8 @@ async def test_index_start_spawns_once(service):

 async def test_index_start_no_roots(service):
     service.settings = lambda: Settings()
-    assert await service.handle({"t": "index_start"}) == {
-        "t": "error",
-        "for": "index_start",
-        "code": "no-roots",
-        "reason": "No folders are selected. Pick folders in setup first.",
-    }
+    assert await service.handle({"t": "index_start"}) == errors.reply(
+        "index_start", errors.no_roots())
     assert not service.test_calls


@@ -333,26 +330,33 @@ async def test_failed_index_exit_broadcasts_progress_and_error(service, exit_cod
     final, error = service.test_pushes[-2:]
     assert final["running"] is False
     assert final["exit"] == exit_code
-    assert error == {
-        "t": "error",
-        "for": "index_start",
-        "code": "runtime-failed",
-        "reason": f"Indexing exited with code {exit_code}. "
-        f"See {service.data_dir / 'index/reindex.log'}.",
-    }
+    log = service.data_dir / "index/reindex.log"
+    assert error == errors.reply("index_start", errors.index_exited(exit_code, log))
+    assert error["log"] == str(log)


 async def test_errors_carry_for_and_no_seq(service, tmp_path):
+    failure = errors.scan_failed("/h", "Permission denied")
+
     def failed(**kw):
-        raise OSError("scan broke")
+        raise errors.UserFailure(failure)

     service.top = failed
     server = IpcServer(tmp_path / "ui.sock", State(), setup=service)
     writer = Writer()
     await server.dispatch(writer, {"t": "discover_start", "seq": 7, "id": "wrong"})
-    assert writer.messages == [
-        {"t": "error", "for": "discover_start", "code": "scan-failed", "reason": "scan broke"}
-    ]
+    assert writer.messages == [errors.reply("discover_start", failure)]
+
+
+@pytest.mark.parametrize("kind", ["index_start", "discover_start", "runtime_status"])
+async def test_unexpected_failure_is_internal_whatever_the_request(service, kind):
+    def broken(*args, **kwargs):
+        raise ValueError("shell.json is not valid JSON")
+
+    service.settings = service.top = broken
+    service.runtime.status = broken
+    reply = await service.handle({"t": kind})
+    assert reply == errors.reply(kind, errors.internal("shell.json is not valid JSON"))


 @pytest.mark.parametrize("kind", sorted(SetupService.TYPES))
@@ -467,7 +471,7 @@ async def test_ipc_dispatch_exception_uses_for_without_search_sequence(service,
     server = IpcServer(tmp_path / "ui.sock", State(), setup=service)
     writer = Writer()
     await server.dispatch(writer, {"t": "runtime_status", "seq": 9, "id": "search"})
-    assert writer.messages == [{"t": "error", "for": "runtime_status", "reason": "bad service"}]
+    assert writer.messages == [errors.reply("runtime_status", errors.internal("bad service"))]


 async def test_setup_requests_after_hello_are_dispatched(service, tmp_path):
@@ -730,7 +734,8 @@ async def test_initial_count_broadcast_failure_finishes_without_starting_a_worke
     await service.handle({'t': 'discover_start'})
     await asyncio.gather(*service._discovery)
     assert pushes == [{'t': 'discover_counts', 'root': '/h', 'counts': {}, 'done': True,
-                       'seconds': None, 'error': 'Cannot send counts'}]
+                       'seconds': None,
+                       'error': errors.scan_failed('/h', 'Cannot send counts').to_dict()}]
     assert service.test_walks[0].done and service.test_walks[0].stopped
     assert '/h' not in service._walked

@@ -757,9 +762,7 @@ async def test_binds_get_failure_names_the_request(service):

     service.run = run
     reply = await service.handle({"t": "binds_get"})
-    assert reply["t"] == "error" and reply["for"] == "binds_get"
-    assert reply["code"] == "binds-failed"
-    assert reply["reason"].startswith("Could not read your Hyprland bindings")
+    assert reply == errors.reply("binds_get", errors.binds_failed("hyprctl"))


 @pytest.mark.parametrize("output,code", [("", 1), ("not JSON", 0), ("[broken", 0),
@@ -770,17 +773,18 @@ async def test_binds_get_rejects_failed_or_malformed_output(service, output, cod
     service.run = lambda argv, **kw: subprocess.CompletedProcess(argv, code, output, "failed")
     reply = await service.handle({"t": "binds_get"})
     assert reply["t"] == "error" and reply["code"] == "binds-failed"
-    assert reply["reason"].startswith("Could not read your Hyprland bindings")
+    assert reply["fix"] == {"kind": "retry"}


-@pytest.mark.parametrize("error", [
-    FileNotFoundError(2, "No such file or directory", "hyprctl"),
-    OSError("Cannot read bindings."),
+@pytest.mark.parametrize("error,detail", [
+    (FileNotFoundError(2, "No such file or directory", "hyprctl"),
+     "hyprctl: No such file or directory. The shortcut was not saved."),
+    (OSError("Cannot read bindings."), "Cannot read bindings. The shortcut was not saved."),
 ])
-async def test_binds_get_failure_has_one_clean_sentence(service, error):
+async def test_binds_get_failure_keeps_the_cause(service, error, detail):
     def run(argv, **kw):
         raise error

     service.run = run
     reply = await service.handle({"t": "binds_get"})
-    assert reply["reason"] == "Could not read your Hyprland bindings."
+    assert reply["code"] == "binds-failed" and reply["detail"] == detail
```

`tests/helper/test_ipc_search.py`: `warm_failed.error`, `degraded` objects, search `error` replies with `seq`, the CLI prints title and detail, and a start failure's own object reaches both `warm_failed` and `degraded`. `test_waiting_reindex_stops_warm_server_and_holds_intent` has a local list named `errors` that would shadow the new module import, so it is renamed to `raised`.

```diff
diff --git a/tests/helper/test_ipc_search.py b/tests/helper/test_ipc_search.py
index 0c40cc5..2ab807c 100644
--- a/tests/helper/test_ipc_search.py
+++ b/tests/helper/test_ipc_search.py
@@ -6,6 +6,7 @@ from pathlib import Path

 import pytest
 from fakes.embedder import FakeEmbedder
+from omafindd import errors
 from omafindd.crawler import crawl
 from omafindd.extractors import Segment
 from omafindd.ipc import IpcServer
@@ -91,7 +92,7 @@ async def test_item_shape_and_same_seq_later_reply(store, tmp_path):
     await service.stop()


-async def test_warm_failed_reports_reason(tmp_path):
+async def test_warm_failed_reports_the_error(tmp_path):
     from omafindd.embedder import EmbeddingError
     from omafindd.service import SearchService

@@ -101,11 +102,36 @@ async def test_warm_failed_reports_reason(tmp_path):

     service = SearchService(tmp_path, lambda: Settings(), Failed(), State())
     reply = await service.handle({"t": "warm"})
-    assert reply["t"] == "warm_failed"
-    assert reply["reason"] == "Vulkan device lost"
+    assert reply == {"t": "warm_failed",
+                     "error": errors.embedding_unavailable("Vulkan device lost").to_dict()}
     await service.stop()


+async def test_start_failure_keeps_its_error_object(store, tmp_path):
+    from omafindd.embedder import EmbeddingError
+    from omafindd.service import SearchService
+
+    await seeded_search(store, tmp_path)
+    failure = errors.server_start_failed("it exited with code 1", tmp_path / "llama-server.log")
+
+    class Failed(FakeEmbedder):
+        async def start(self, mode):
+            raise EmbeddingError("Embedding server failed to start", user_error=failure)
+
+    service = SearchService(
+        store.path.parent, lambda: Settings(), Failed(), State(model="ready"),
+        volume_resolver=lambda path, **kwargs: ("v", tmp_path), mounts_resolver=lambda: {}
+    )
+    try:
+        assert await service.handle({"t": "warm"}) == {"t": "warm_failed",
+                                                       "error": failure.to_dict()}
+        reply = await service.handle({"t": "search", "seq": 1, "q": "lunar"})
+        assert reply["degraded"] == failure.to_dict()
+        assert reply["items"][0]["name"] == "notes.txt"
+    finally:
+        await service.stop()
+
+
 async def test_warm_server_stops_after_idle_timeout(tmp_path):
     from omafindd.service import SearchService

@@ -130,7 +156,7 @@ async def test_daemon_sees_db_added_by_cli(tmp_path):
         volume_resolver=lambda path, **kwargs: ("v", tmp_path),
     )
     first = await service.handle({"t": "search", "seq": 1, "q": "lunar"})
-    assert first["code"] == "no-index"
+    assert first == {"t": "error", "seq": 1, **errors.no_index().to_dict()}
     store = Store(tmp_path / "index/v.sqlite", volume="v", mount=tmp_path)
     await seeded_search(store, tmp_path)
     second = await service.handle({"t": "search", "seq": 2, "q": "lunar"})
@@ -263,7 +289,7 @@ async def test_socket_dispatch_stores_connection_latest_items(store, tmp_path):
     "response,code",
     [
         ({"t": "results", "seq": 1, "items": []}, 0),
-        ({"t": "error", "code": "no-index", "reason": "Run omafind reindex"}, 1),
+        ({"t": "error", "seq": 1, **errors.no_index().to_dict()}, 1),
         (False, 3),
     ],
 )
@@ -276,7 +302,7 @@ def test_cli_search_exit_codes(cli, env, capsys, response, code):
     if code == 0:
         assert json.loads(output.out) == response
     elif code == 1:
-        assert "omafind reindex" in output.err
+        assert output.err == "Nothing is indexed yet. Open setup and start the first index.\n"


 @pytest.mark.parametrize(
@@ -575,7 +601,7 @@ async def test_query_while_server_starting_returns_words_without_waiting(
                     await service.yield_to_indexer()
                     fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                     locked = await service.handle(query)
-                    assert locked['degraded'] == 'indexing in progress'
+                    assert locked['degraded'] == errors.index_running().to_dict()
             embedder.blocked = True
         elif startup == 'warm-request':
             warming = asyncio.create_task(service.handle({'t': 'warm'}))
@@ -584,7 +610,7 @@ async def test_query_while_server_starting_returns_words_without_waiting(
         await asyncio.wait_for(entered.wait(), .5)
         assert not release.is_set()
         assert reply['legs'] == ['words']
-        assert reply['degraded'] == 'the embedding server is starting'
+        assert reply['degraded'] == errors.server_starting().to_dict()
         assert reply['items'][0]['name'] == 'notes.txt'
         assert reply['items'][0]['leg'] == 'words'
         repeated = await asyncio.wait_for(service.handle(query), .1)
@@ -624,11 +650,12 @@ async def test_background_startup_failure_is_reported_by_next_query(store, tmp_p
     )
     query = {'t': 'search', 'seq': 1, 'q': 'lunar'}
     try:
-        assert (await service.handle(query))['degraded'] == 'the embedding server is starting'
+        assert (await service.handle(query))['degraded'] == errors.server_starting().to_dict()
         release.set()
         await asyncio.wait_for(failed.wait(), .5)
         reply = await service.handle(query)
-        assert reply['degraded'] == 'the embedding server did not start'
+        assert reply['degraded'] == errors.embedding_unavailable(
+            'the embedding server did not start').to_dict()
         assert reply['items'][0]['name'] == 'notes.txt'
         assert service._index_lock is None
         assert service.embedder.starts == 1
@@ -760,9 +787,9 @@ async def test_reindex_lock_forces_words_and_rejects_warm(store, tmp_path, legs)
         with (tmp_path / "index.lock").open("w") as lock:
             fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
             warm = await service.handle({"t": "warm"})
-            assert warm == {"t": "warm_failed", "reason": "indexing in progress"}
+            assert warm == {"t": "warm_failed", "error": errors.index_running().to_dict()}
             reply = await service.handle({"t": "search", "seq": 1, "q": "lunar", "legs": legs})
-            assert reply["degraded"] == "indexing in progress"
+            assert reply["degraded"] == errors.index_running().to_dict()
             assert reply["legs"] == ["words"]
             assert reply["items"][0]["leg"] == "words"
             assert embedder.starts == 0
@@ -923,21 +950,21 @@ async def test_waiting_reindex_stops_warm_server_and_holds_intent(tmp_path, monk
             release.wait(2)
             await super().stop()

-    errors = []
+    raised = []

     def index():
         try:
             asyncio.run(reindex([], directory=tmp_path, embedder=Indexer()))
         except BaseException as error:
-            errors.append(error)
+            raised.append(error)

     async def wait(event):
         for _ in range(100):
-            if event.is_set() or errors:
+            if event.is_set() or raised:
                 break
             await asyncio.sleep(0.01)
-        if errors:
-            raise errors[0]
+        if raised:
+            raise raised[0]
         assert event.is_set()

     monkeypatch.setattr(fcntl, "flock", observe)
@@ -951,11 +978,11 @@ async def test_waiting_reindex_stops_warm_server_and_holds_intent(tmp_path, monk
         await wait(acquired)
         reply = await service.handle({"t": "search", "seq": 1, "q": "lunar"})
         assert reply["legs"] == ["words"]
-        assert reply["degraded"] == "indexing in progress"
+        assert reply["degraded"] == errors.index_running().to_dict()
         assert reply["items"][0]["name"] == "notes.txt"
         assert service.embedder.mode is None
         assert await service.handle({"t": "warm"}) == {
-            "t": "warm_failed", "reason": "indexing in progress"
+            "t": "warm_failed", "error": errors.index_running().to_dict()
         }
         assert capsys.readouterr().err.splitlines() == [
             "waiting index.lock", "queued 0"
@@ -1052,14 +1079,15 @@ async def test_service_exception_replies_with_error_and_keeps_connection(tmp_pat
         reader.feed_eof()
         await client
     replies = [json.loads(line) for line in writer.data.splitlines()]
-    assert replies[1] == {"t": "error", "seq": 7, "reason": str(error)}
+    assert replies[1] == {"t": "error", "seq": 7, **errors.internal(str(error)).to_dict()}
     assert replies[2] == {"t": "results", "seq": 8, "items": []}


-def test_cli_service_error_prints_reason_and_exits_one(cli, env, capsys):
-    reply = {"t": "error", "seq": 1, "reason": "no such table: meta"}
+def test_cli_service_error_prints_title_and_detail_and_exits_one(cli, env, capsys):
+    reply = {"t": "error", "seq": 1, **errors.internal("no such table: meta").to_dict()}
     assert cli.main(["search", "--json", "lunar"], env, request=lambda *args: reply) == 1
-    assert capsys.readouterr().err == "no such table: meta\n"
+    assert capsys.readouterr().err == (
+        "Something failed inside the omafind service. No such table: meta.\n")


 @pytest.mark.parametrize("kinds", [None, "image", ["img"], [1], [{}]])
@@ -1069,7 +1097,8 @@ async def test_service_rejects_invalid_kinds(tmp_path, kinds):
     service = SearchService(tmp_path / "index", lambda: Settings(), FakeEmbedder(), State())
     try:
         reply = await service.handle({"t": "search", "seq": 1, "q": "needle", "kinds": kinds})
-        assert reply["code"] == "bad-request"
+        assert reply == {"t": "error", "seq": 1,
+                         **errors.bad_request("Invalid search arguments").to_dict()}
     finally:
         await service.stop()

```

`tests/helper/test_ipc_overlay.py`: preview and open errors become objects, a renderer crash is `internal` with the item id, and a launch failure is `open_failed` with `open-failed`.

```diff
diff --git a/tests/helper/test_ipc_overlay.py b/tests/helper/test_ipc_overlay.py
index b995a7b..8295326 100644
--- a/tests/helper/test_ipc_overlay.py
+++ b/tests/helper/test_ipc_overlay.py
@@ -3,7 +3,7 @@ import sqlite3
 from types import SimpleNamespace

 import pytest
-from omafindd import opener, preview
+from omafindd import errors, opener, preview
 from omafindd.ipc import IpcServer
 from omafindd.settings import Settings
 from omafindd.state import State
@@ -57,7 +57,23 @@ async def test_preview_latest_results(server, tmp_path, monkeypatch, kind, mode)
     assert calls == [(item, "talk")]
     other = Writer()
     await server.dispatch(other, {"t": "preview", "id": "hit"})
-    assert other.messages[-1]["code"] == "missing"
+    assert other.messages[-1] == {"t": "error", "id": "hit",
+                                  **errors.file_missing("The file").to_dict()}
+
+
+async def test_preview_failure_is_internal_with_the_item_id(server, tmp_path, monkeypatch):
+    path = tmp_path / "a.pdf"
+    path.touch()
+    writer = Writer()
+    server._results[writer] = {"hit": {"id": "hit", "kind": "pdf", "path": str(path)}}
+
+    def render(item, query):
+        raise RuntimeError("pdftoppm crashed")
+
+    monkeypatch.setattr(preview, "render", render)
+    await server.dispatch(writer, {"t": "preview", "id": "hit"})
+    assert writer.messages[-1] == {"t": "error", "id": "hit",
+                                   **errors.internal("pdftoppm crashed").to_dict()}


 async def test_open_reveal_and_preview_jump(server, tmp_path, monkeypatch):
@@ -80,20 +96,39 @@ async def test_open_reveal_and_preview_jump(server, tmp_path, monkeypatch):
     assert calls[-1][1]["how"] == "reveal"


-@pytest.mark.parametrize("offline,exists,reason", [(True, True, "offline"),
-                                                  (False, False, "missing")])
+@pytest.mark.parametrize("offline,exists,error", [
+    (True, True, errors.drive_not_mounted("Photos2024")),
+    (False, False, errors.file_missing("a")),
+])
 async def test_open_refuses_offline_or_missing(server, tmp_path, monkeypatch,
-                                              offline, exists, reason):
+                                              offline, exists, error):
     path = tmp_path / "a"
     if exists:
         path.touch()
     writer = Writer()
-    server._results[writer] = {"hit": {"id": "hit", "path": str(path), "offline": offline}}
+    server._results[writer] = {"hit": {"id": "hit", "path": str(path), "offline": offline,
+                                       "label": "Photos2024"}}
     monkeypatch.setattr(opener, "launch", lambda *args, **kw: pytest.fail("launched"))
     await server.dispatch(writer, {"t": "open", "id": "hit", "how": "open"})
-    assert writer.messages[-1] == {"t": "open_failed", "id": "hit", "reason": reason}
+    assert writer.messages[-1] == {"t": "open_failed", "id": "hit", "error": error.to_dict()}
     await server.dispatch(writer, {"t": "open", "id": "unknown", "how": "open"})
-    assert writer.messages[-1]["reason"] == "missing"
+    assert writer.messages[-1]["error"] == errors.file_missing("The file").to_dict()
+
+
+async def test_open_launch_failure_names_the_program(server, tmp_path, monkeypatch):
+    path = tmp_path / "clip.mp4"
+    path.touch()
+    writer = Writer()
+    server._results[writer] = {"hit": {"id": "hit", "kind": "video", "path": str(path)}}
+
+    def launch(item, **kw):
+        raise FileNotFoundError(2, "No such file or directory", "mpv")
+
+    monkeypatch.setattr(opener, "launch", launch)
+    await server.dispatch(writer, {"t": "open", "id": "hit", "how": "open"})
+    assert writer.messages[-1] == {
+        "t": "open_failed", "id": "hit",
+        "error": errors.open_failed("clip.mp4", "mpv: No such file or directory").to_dict()}


 async def test_status_reply_and_time_gated_push(server, tmp_path):
@@ -325,8 +360,9 @@ async def test_open_prefers_client_line_and_rejects_bad_lines(server, tmp_path,
     assert calls[-1]["loc"] == 212
     for line in (0, -3, "7", True, 2.5, None):
         await server.dispatch(writer, {"t": "open", "id": "hit", "how": "open", "line": line})
-        assert writer.messages[-1] == {"t": "error", "id": "hit", "for": "open",
-                                       "code": "bad-request", "reason": "Invalid open arguments"}
+        assert writer.messages[-1] == {
+            "t": "error", "id": "hit", "for": "open",
+            **errors.bad_request("Invalid open arguments").to_dict()}
     assert len(calls) == 2


```

`tests/helper/test_ipc_volumes.py` and `tests/helper/test_permissions.py`:

```diff
diff --git a/tests/helper/test_ipc_volumes.py b/tests/helper/test_ipc_volumes.py
index e352905..c9e0bbb 100644
--- a/tests/helper/test_ipc_volumes.py
+++ b/tests/helper/test_ipc_volumes.py
@@ -3,6 +3,7 @@ from pathlib import Path
 from types import SimpleNamespace

 import pytest
+from omafindd import errors
 from omafindd.ipc import IpcServer
 from omafindd.service import SearchService
 from omafindd.settings import Settings
@@ -103,7 +104,7 @@ async def test_volume_and_paused_replayed_after_hello(tmp_path):
     server = IpcServer(tmp_path / 'ui.sock', State(), peer_uid=lambda _: __import__('os').getuid())
     volume = {'t': 'volume', 'uuid': 'usb', 'label': 'Photos2024', 'fs': 'exfat',
               'size': 123, 'mount': '/media/Photos2024', 'online': True, 'known': False}
-    paused = {'t': 'paused', 'reason': 'disk', 'free_gb': 1.4, 'need_gb': 2}
+    paused = {'t': 'paused', 'error': errors.disk_low().to_dict(), 'free_gb': 1.4, 'need_gb': 2}
     server.replay = lambda: [volume, paused]
     reader, writer = memory_client(server)
     try:
@@ -229,7 +230,7 @@ async def test_disk_transitions_are_broadcast_and_replayed(freshness, monkeypatc
     await freshness.check_disk()
     await freshness.check_disk()
     assert freshness.test_pushes == [
-        {'t': 'paused', 'reason': 'disk', 'free_gb': 1.4, 'need_gb': 2}]
+        {'t': 'paused', 'error': errors.disk_low().to_dict(), 'free_gb': 1.4, 'need_gb': 2}]
     assert freshness.replay() == freshness.test_pushes
     monkeypatch.setattr(freshness.guard, 'free_bytes', lambda: 2_100_000_000)
     await freshness.check_disk()
@@ -372,7 +373,8 @@ async def test_unverified_meaning_only_search_returns_words(tmp_path):
         result = await service.handle({'t': 'search', 'seq': 1, 'q': 'note',
                                        'legs': ['meaning']})
         assert result['legs'] == ['words']
-        assert result['degraded'] == 'embedding model failed verification'
+        assert result['degraded'] == errors.embedding_unavailable(
+            'embedding model failed verification').to_dict()
         assert result['items'][0]['name'] == 'note.txt'
     finally:
         await service.stop()
```
```diff
diff --git a/tests/helper/test_permissions.py b/tests/helper/test_permissions.py
index d6171b7..895f431 100644
--- a/tests/helper/test_permissions.py
+++ b/tests/helper/test_permissions.py
@@ -82,7 +82,7 @@ def test_fix_dirs_is_shallow_and_does_not_follow_symlinks(tmp_path):


 def test_bad_model_digest_makes_search_words_only(tmp_path, monkeypatch):
-    from omafindd import models, paths
+    from omafindd import errors, models, paths
     from omafindd.state import State

     monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
@@ -118,7 +118,8 @@ def test_bad_model_digest_makes_search_words_only(tmp_path, monkeypatch):
         try:
             reply = await service.handle({'t': 'search', 'seq': 1, 'q': 'note'})
             assert reply['legs'] == ['words']
-            assert reply['degraded'] == 'embedding model failed verification'
+            assert reply['degraded'] == errors.embedding_unavailable(
+                'embedding model failed verification').to_dict()
             assert reply['items'][0]['name'] == 'note.txt'
         finally:
             await service.stop()
```

`tests/helper/test_install.py`: `runtime_progress.error` replaces `reason`, with `build-failed`, `build-no-scope`, `model-verify-failed`, `model-download-failed` and `internal`.

```diff
diff --git a/tests/helper/test_install.py b/tests/helper/test_install.py
index b00f8f2..5a6e9b0 100644
--- a/tests/helper/test_install.py
+++ b/tests/helper/test_install.py
@@ -3,7 +3,7 @@ import os
 from types import SimpleNamespace

 import pytest
-from omafindd import models
+from omafindd import errors, models
 from omafindd.install import RuntimeJob, gpu_name


@@ -152,23 +152,55 @@ async def test_pause_during_download_stops_at_next_chunk_and_resume_continues(jo

 async def test_build_failure_reports_last_stderr_line(job_factory):
     job, _, _ = job_factory(process=Process(1, b"first\nlast error\n"))
+    assert job.snapshot()["error"] is None and "reason" not in job.snapshot()
     await job.start()
     await finish(job)
     assert job.snapshot()["build"]["state"] == "failed"
-    assert job.snapshot()["reason"] == (
-        "The runtime build failed: last error. "
-        "Run bin/omafind build-runtime in a terminal for the full log."
-    )
+    assert job.snapshot()["error"] == errors.build_failed("last error").to_dict()


-async def test_digest_mismatch_fails_with_resume_hint(job_factory):
+async def test_digest_mismatch_fails_with_model_verify_failed(job_factory):
     job, _, _ = job_factory(valid=lambda directory: {f.name: False for f in models.FILES})
     await job.start()
     await finish(job)
     assert job.snapshot()["state"] == "failed"
-    assert job.snapshot()["reason"] == (
-        f"Model sha256 mismatch: {models.FILES[0].name}. Press Resume to download it again."
-    )
+    assert job.snapshot()["error"] == errors.model_verify_failed(models.FILES[0].name).to_dict()
+
+
+@pytest.mark.parametrize("raised,expected", [
+    (OSError("connection refused"), errors.model_download_failed("connection refused")),
+    (ValueError(f"Model sha256 mismatch: {models.FILES[1].name}"),
+     errors.model_verify_failed(models.FILES[1].name)),
+])
+async def test_download_failure_names_its_cause(job_factory, raised, expected):
+    def fetch(directory, *, progress):
+        raise raised
+
+    job, _, _ = job_factory(download=fetch)
+    await job.start()
+    await finish(job)
+    assert job.snapshot()["state"] == "failed"
+    assert job.snapshot()["build"]["state"] == "ok"
+    assert job.snapshot()["error"] == expected.to_dict()
+
+
+async def test_unexpected_failure_is_internal(job_factory):
+    def broken(directory):
+        raise RuntimeError("disk vanished")
+
+    job, _, _ = job_factory(valid=broken)
+    await job.start()
+    await finish(job)
+    assert job.snapshot()["error"] == errors.internal("disk vanished").to_dict()
+
+
+async def test_restart_clears_the_error(job_factory):
+    job, _, _ = job_factory(process=Process(1, b"boom\n"))
+    await job.start()
+    await finish(job)
+    assert job.snapshot()["error"]["code"] == "build-failed"
+    assert (await job.start())["error"] is None
+    await finish(job)


 async def test_existing_runtime_reports_installed_without_seconds(job_factory, tmp_path):
@@ -239,7 +271,7 @@ async def test_build_refuses_unavailable_memory_scope(job_factory, monkeypatch):
     await job.start()
     await finish(job)
     assert job.snapshot()["state"] == "failed"
-    assert "memory" in job.snapshot()["reason"]
+    assert job.snapshot()["error"] == errors.build_no_scope().to_dict()
     assert not calls


```

`tests/helper/test_cli.py`: `omafind discover --json` prints a `UserFailure` as title and detail.

```diff
diff --git a/tests/helper/test_cli.py b/tests/helper/test_cli.py
index b9f0dda..67224fa 100644
--- a/tests/helper/test_cli.py
+++ b/tests/helper/test_cli.py
@@ -363,6 +363,21 @@ def test_discover_failure_exits_1_with_one_stderr_line(cli, env, monkeypatch, ca
     assert capsys.readouterr().err.splitlines() == ['scan failed more details']


+def test_discover_user_failure_prints_title_and_detail(cli, env, monkeypatch, capsys):
+    from omafindd import discovery, errors
+
+    python = Path(env['HOME']) / '.local/share/omafind/venv/bin/python'
+    monkeypatch.setattr(sys, 'prefix', str(python.parent.parent))
+
+    def snapshot(**kwargs):
+        raise errors.UserFailure(errors.drive_not_mounted('Photos2024'))
+
+    monkeypatch.setattr(discovery, 'snapshot', snapshot)
+    assert cli.main(['discover', '--json', '--volume', 'usb'], env) == 1
+    assert capsys.readouterr().err == (
+        'Photos2024 is not connected. Connect it, then press Retry.\n')
+
+
 def test_reindex_incremental_passes_force_false(cli, env, monkeypatch):
     from omafindd import indexing
     from omafindd.settings import Settings
```

- [ ] **Step 2: Run them to see them fail**

```bash
uv run --project helper pytest -q tests/helper/test_errors.py tests/helper/test_embedder.py::test_embedding_error_carries_an_optional_error_object tests/helper/test_discovery.py tests/helper/test_diskguard.py tests/helper/test_ipc_setup.py tests/helper/test_ipc_search.py tests/helper/test_ipc_overlay.py tests/helper/test_ipc_volumes.py tests/helper/test_permissions.py tests/helper/test_install.py tests/helper/test_cli.py::test_discover_user_failure_prints_title_and_detail
```

Expected: 73 failures. Representative ones:
- `test_copy_rules[index_running]`: `AttributeError: module 'omafindd.errors' has no attribute 'index_running'`.
- `test_embedding_error_carries_an_optional_error_object`: `TypeError: ... unexpected keyword argument 'user_error'`.
- `test_list_dirs_hides_dot_and_heavy_and_reports_missing`: `assert 'missing' == {'code': 'scan-failed', ...}`.
- `test_failed_index_exit_broadcasts_progress_and_error[1]`: `{'code': 'runtime-failed'} != {'code': 'index-exited'}`.
- `test_unexpected_failure_is_internal_whatever_the_request[index_start]`: `{'code': 'runtime-failed'} != {'code': 'internal'}`.
- `test_warm_failed_reports_the_error`: `{"t": "warm_failed", "reason": "Vulkan device lost"}` does not equal the `error` form.
- `test_open_refuses_offline_or_missing[...]`: `{'reason': 'offline'}` versus `{'error': {...}}`.
- `test_build_failure_reports_last_stderr_line`: `KeyError: 'error'`.

- [ ] **Step 3: Add `index_running` and `EmbeddingError.user_error`**

`helper/omafindd/errors.py` (hunk against Task 1's wrapped file):

```diff
diff --git a/helper/omafindd/errors.py b/helper/omafindd/errors.py
index 8f561d1..553458a 100644
--- a/helper/omafindd/errors.py
+++ b/helper/omafindd/errors.py
@@ -171,6 +171,12 @@ def disk_low() -> UserError:
     )


+def index_running() -> UserError:
+    return UserError(
+        "index-running", "Indexing is running.", "Showing keyword matches until it finishes."
+    )
+
+
 def index_exited(code: int, log=None) -> UserError:
     return UserError(
         "index-exited",
```

`helper/omafindd/embedder.py`:

```diff
diff --git a/helper/omafindd/embedder.py b/helper/omafindd/embedder.py
index fb54f35..de62610 100644
--- a/helper/omafindd/embedder.py
+++ b/helper/omafindd/embedder.py
@@ -39,7 +39,11 @@ def loopback_url(url):


 class EmbeddingError(Exception):
-    pass
+    user_error = None
+
+    def __init__(self, *args, user_error=None):
+        super().__init__(*args)
+        self.user_error = user_error


 class EmbeddingRejected(EmbeddingError):
```

- [ ] **Step 4: Discovery and disk messages carry the object**

`helper/omafindd/discovery.py`. `top` raises `UserFailure` at the cause: `drive-not-mounted` (named by its lsblk label when the device is still listed) and `scan-failed` for an unreadable root. Walk, child and listing errors become `scan-failed` objects. `list_dirs` now catches every `OSError`, so the three legacy codes collapse into one object whose detail is the OS message.

```diff
diff --git a/helper/omafindd/discovery.py b/helper/omafindd/discovery.py
index 7e59ae1..4c90a4d 100644
--- a/helper/omafindd/discovery.py
+++ b/helper/omafindd/discovery.py
@@ -6,7 +6,7 @@ import threading
 import time
 from pathlib import Path

-from . import rules
+from . import errors, rules

 KINDS = ('text', 'pdf', 'image', 'video', 'audio')
 RATES = {
@@ -110,6 +110,24 @@ def folders(path) -> list[dict]:
     return rows


+def _scanned(path) -> list[dict]:
+    try:
+        return folders(path)
+    except OSError as error:
+        failure = errors.scan_failed(str(path), error.strerror or str(error))
+        raise errors.UserFailure(failure) from error
+
+
+def _label(lsblk: dict, uuid: str) -> str | None:
+    devices = list(lsblk.get('blockdevices', []))
+    while devices:
+        device = devices.pop()
+        if device.get('uuid') == uuid and device.get('label'):
+            return device['label']
+        devices.extend(device.get('children', []))
+    return None
+
+
 def top(*, home: Path, volume: str | None = None, run=subprocess.run, lsblk=None, xdg=None,
         volume_of=None) -> dict:
     """The first level of the Folders step: one directory read per root.
@@ -126,13 +144,13 @@ def top(*, home: Path, volume: str | None = None, run=subprocess.run, lsblk=None
     if volume is not None:
         mount = next((path for uuid, path in volumes if uuid == volume), None)
         if mount is None:
-            raise ValueError("That drive is not mounted. Plug it in and try again.")
-        rows = [dict(row, xdg=False, volume=volume) for row in folders(mount)]
+            raise errors.UserFailure(errors.drive_not_mounted(_label(lsblk, volume) or "The drive"))
+        rows = [dict(row, xdg=False, volume=volume) for row in _scanned(mount)]
         return {"roots": [{"path": str(mount), "volume": volume}], "folders": rows}
     xdg = xdg_dirs(home) if xdg is None else xdg
     picks = {str(xdg[name]) for name in XDG_PICKS if name in xdg}
     lookup = _volume_lookup(lsblk) if volume_of is None else volume_of
-    rows = [dict(row, xdg=row["path"] in picks) for row in folders(home)]
+    rows = [dict(row, xdg=row["path"] in picks) for row in _scanned(home)]
     roots = [{"path": str(home), "volume": lookup(home)[0]}]
     for uuid, mount in volumes:
         roots.append({"path": str(mount), "volume": uuid})
@@ -269,7 +287,8 @@ class Walk:
                     changed, last = set(), now
         except OSError as error:
             if not self._stop:
-                self.error = str(error) or type(error).__name__
+                self.error = errors.scan_failed(
+                    root, error.strerror or str(error) or type(error).__name__).to_dict()
         finally:
             if listing is not None:
                 listing.close()
@@ -297,7 +316,8 @@ def children(path, walk=None) -> dict:
     try:
         rows = folders(path)
     except OSError as error:
-        return {"path": str(path), "dirs": [], "error": error.strerror or str(error)}
+        return {"path": str(path), "dirs": [],
+                "error": errors.scan_failed(str(path), error.strerror or str(error)).to_dict()}
     for row in rows:
         row["counts"] = walk.count(row["path"]) if walk is not None else None
         row["evidence"] = walk.dataset(row["path"]) if walk is not None else None
@@ -370,10 +390,6 @@ def list_dirs(path: str, *, home: Path) -> dict:
                                      if not entry.name.startswith('.')
                                      and entry.name not in rules.HEAVY_GLOBS
                                      and entry.is_dir()), key=lambda n: (n.casefold(), n))[:500]
-    except FileNotFoundError:
-        result['error'] = 'missing'
-    except NotADirectoryError:
-        result['error'] = 'not-a-directory'
-    except PermissionError:
-        result['error'] = 'denied'
+    except OSError as error:
+        result['error'] = errors.scan_failed(str(absolute), error.strerror or str(error)).to_dict()
     return result
```

`helper/omafindd/diskguard.py`:

```diff
diff --git a/helper/omafindd/diskguard.py b/helper/omafindd/diskguard.py
index cb432e9..6e7f669 100644
--- a/helper/omafindd/diskguard.py
+++ b/helper/omafindd/diskguard.py
@@ -1,6 +1,8 @@
 import asyncio
 import os

+from . import errors
+
 NEED_BYTES = 2_000_000_000


@@ -23,7 +25,8 @@ class DiskGuard:
             return None
         self.paused = low
         if low:
-            return {'t': 'paused', 'reason': 'disk', 'free_gb': round(free / 1e9, 1), 'need_gb': 2}
+            return {'t': 'paused', 'error': errors.disk_low().to_dict(),
+                    'free_gb': round(free / 1e9, 1), 'need_gb': 2}
         return {'t': 'resumed'}


```

- [ ] **Step 5: `SetupService` takes the code from the cause**

`helper/omafindd/setup.py`. `_error` goes away. Bad requests go through `errors.bad_request` (its detail adds the full stop, so the reasons lose theirs). `handle` passes a `UserFailure` through and turns anything else into `internal`. `_binds` raises `binds-failed` with the real cause. An `OSError` with a file name reads `hyprctl: No such file or directory` instead of `[Errno 2] ...`. Walk failures become `scan-failed`. No roots becomes `no-roots`, and the index exit broadcast becomes `index-exited` with the `reindex.log` path.

```diff
diff --git a/helper/omafindd/setup.py b/helper/omafindd/setup.py
index 7a61bc3..178f858 100644
--- a/helper/omafindd/setup.py
+++ b/helper/omafindd/setup.py
@@ -10,7 +10,7 @@ import time
 from contextlib import closing
 from pathlib import Path

-from . import bindings, discovery
+from . import bindings, discovery, errors
 from .install import RuntimeJob


@@ -89,10 +89,6 @@ class SetupService:
         self._final = True
         self._mounts = {}

-    @staticmethod
-    def _error(kind, code, reason):
-        return {"t": "error", "for": kind, "code": code, "reason": reason}
-
     async def handle(self, message: dict, *, client=None) -> dict:
         kind = message["t"]
         try:
@@ -114,7 +110,7 @@ class SetupService:
                 token = self._client_tokens.setdefault(client, object())
                 volume = message.get("volume")
                 if volume is not None and (not isinstance(volume, str) or not volume):
-                    return self._error(kind, "bad-request", "Invalid discovery volume.")
+                    return errors.reply(kind, errors.bad_request("Invalid discovery volume"))
                 body = await asyncio.to_thread(self.top, home=self.home, volume=volume)
                 device = await asyncio.to_thread(self.estimate_device, self.home)
                 if self._client_tokens.get(client) is not token:
@@ -134,7 +130,7 @@ class SetupService:
                 token = self._client_tokens.setdefault(client, object())
                 path = message.get("path")
                 if not isinstance(path, str) or not Path(path).is_absolute():
-                    return self._error(kind, "bad-request", "Pick an absolute folder path.")
+                    return errors.reply(kind, errors.bad_request("Pick an absolute folder path"))
                 path = os.path.normpath(path)
                 roots = [root for root in self._roots
                          if path == root or path.startswith(root.rstrip("/") + "/")]
@@ -142,7 +138,8 @@ class SetupService:
                     path == root or path.startswith(root + "/")
                     for root in ("/proc", "/sys", "/dev", "/run")
                 )):
-                    return self._error(kind, "bad-request", "Pick a folder outside system paths.")
+                    failure = errors.bad_request("Pick a folder outside system paths")
+                    return errors.reply(kind, failure)
                 root = max(roots, key=len) if roots else path
                 if not roots:
                     try:
@@ -167,32 +164,28 @@ class SetupService:
                     or not path
                     or not (Path(path).is_absolute() or path == "~" or path.startswith("~/"))
                 ):
-                    return self._error(kind, "bad-request", "Pick an absolute folder path.")
+                    return errors.reply(kind, errors.bad_request("Pick an absolute folder path"))
                 body = await asyncio.to_thread(self.list_dirs, path, home=self.home)
                 return {"t": kind, **body}
             if kind == "drive_decision":
                 uuid, choice = message.get("uuid"), message.get("choice")
                 if not isinstance(uuid, str) or not uuid or choice not in ("scan", "ignore"):
-                    return self._error(kind, "bad-request", "Invalid drive decision.")
+                    return errors.reply(kind, errors.bad_request("Invalid drive decision"))
                 if choice == "ignore":
                     self.ignored.add(uuid)
                 return {"t": kind, "uuid": uuid, "choice": choice}
             if kind == "index_start":
                 volume = message.get("volume")
                 if volume is not None and (not isinstance(volume, str) or not volume):
-                    return self._error(kind, "bad-request", "Invalid indexing volume.")
+                    return errors.reply(kind, errors.bad_request("Invalid indexing volume"))
                 if self._starting is None or self._starting.done():
                     self._starting = asyncio.create_task(self._start_index(volume))
                 return await asyncio.shield(self._starting)
-            return self._error(kind, "bad-request", "Unknown setup request.")
+            return errors.reply(kind, errors.bad_request("Unknown setup request"))
+        except errors.UserFailure as failure:
+            return errors.reply(kind, failure.error)
         except Exception as error:
-            code = (
-                "runtime-failed"
-                if kind.startswith("runtime_") or kind == "index_start"
-                else "binds-failed" if kind == "binds_get"
-                else "scan-failed"
-            )
-            return self._error(kind, code, str(error))
+            return errors.reply(kind, errors.internal(str(error) or type(error).__name__))

     def _binds(self):
         try:
@@ -204,7 +197,10 @@ class SetupService:
             items = bindings.binds_items(bindings.parse_binds(result.stdout))
             return {"t": "binds", "binds": items}
         except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as error:
-            raise OSError("Could not read your Hyprland bindings.") from error
+            reason = (f"{error.filename}: {error.strerror}"
+                      if isinstance(error, OSError) and error.filename and error.strerror
+                      else str(error) or type(error).__name__)
+            raise errors.UserFailure(errors.binds_failed(reason)) from error

     def _track(self, coroutine):
         task = asyncio.create_task(coroutine)
@@ -245,7 +241,7 @@ class SetupService:
                 walk.run(emit)
             except Exception as error:
                 walk.done = True
-                walk.error = str(error) or type(error).__name__
+                walk.error = errors.scan_failed(root, str(error) or type(error).__name__).to_dict()
                 emit({"root": root, "counts": {}, "done": True, "seconds": None,
                       "error": walk.error})

@@ -266,7 +262,7 @@ class SetupService:
             if worker is not None:
                 await asyncio.gather(worker, return_exceptions=True)
             walk.done = True
-            walk.error = str(error) or type(error).__name__
+            walk.error = errors.scan_failed(root, str(error) or type(error).__name__).to_dict()
             try:
                 await self.broadcast({"t": "discover_counts", "root": root, "counts": {},
                                       "done": True, "seconds": None, "error": walk.error})
@@ -323,11 +319,7 @@ class SetupService:
         async with self._index_lock:
             settings = self.settings()
             if not settings.roots and not settings.code_roots:
-                return self._error(
-                    "index_start",
-                    "no-roots",
-                    "No folders are selected. Pick folders in setup first.",
-                )
+                return errors.reply("index_start", errors.no_roots())
             if self.check_disk is not None:
                 await self.check_disk()
             if self.paused() or not self.model_ready():
@@ -513,13 +505,9 @@ class SetupService:
             if not body["running"]:
                 self._final = True
                 if "exit" in body:
+                    log = self.data_dir / "index/reindex.log"
                     await self.broadcast(
-                        self._error(
-                            "index_start",
-                            "runtime-failed",
-                            f"Indexing exited with code {body['exit']}. "
-                            f"See {self.data_dir / 'index/reindex.log'}.",
-                        )
+                        errors.reply("index_start", errors.index_exited(body["exit"], log))
                     )

                 if self._deferred:
```

- [ ] **Step 6: Search replies carry the object, and the start failure keeps its own**

`helper/omafindd/search.py`. `_query` returns the `degraded` object. It prefers the `EmbeddingError.user_error` the start or embed call raised.

```diff
diff --git a/helper/omafindd/search.py b/helper/omafindd/search.py
index 1195ae9..c59d767 100644
--- a/helper/omafindd/search.py
+++ b/helper/omafindd/search.py
@@ -7,6 +7,7 @@ from pathlib import Path

 import numpy as np

+from . import errors
 from .embedder import EmbeddingError
 from .embedding import Embedder, validated
 from .search_text import normalized, pattern, snippet_parts, terms
@@ -262,13 +263,15 @@ class Searcher:
         if not enabled:
             return None, None, 0
         if self.embedder is None:
-            return None, "embedding model unavailable", 0
+            return None, errors.embedding_unavailable("embedding model unavailable").to_dict(), 0
         try:
             await (self.start or self.embedder.start)("text")
             vector = validated(await self.embedder.embed_query(text)).astype(np.float32)
             return vector, None, (time.monotonic() - begun) * 1000
         except (EmbeddingError, OSError, ValueError) as error:
-            return None, str(error), (time.monotonic() - begun) * 1000
+            failure = getattr(error, "user_error", None) or errors.embedding_unavailable(
+                str(error) or type(error).__name__)
+            return None, failure.to_dict(), (time.monotonic() - begun) * 1000

     async def search(self, q: str, *, legs=("words", "meaning"), limit=40, seq=1,
                      kinds=None) -> dict:
```

`helper/omafindd/service.py`. `_warm` returns a `UserError` (or `None`) instead of a string. `_start_query` re-raises it as `EmbeddingError(title, user_error=obj)`, so Task 4's `server-start-failed` object (with its log) survives to `warm_failed.error` and `degraded`. Indexing and starting raise with `index_running()` and `server_starting()`. `_handle` branches on `degraded["code"]` instead of on strings, and search errors keep `seq`.

```diff
diff --git a/helper/omafindd/service.py b/helper/omafindd/service.py
index 6384f4f..bab5234 100644
--- a/helper/omafindd/service.py
+++ b/helper/omafindd/service.py
@@ -4,6 +4,7 @@ import os
 import sqlite3
 from pathlib import Path

+from . import errors
 from .code import configured_roots


@@ -17,6 +18,11 @@ def volume_for(path, **kwargs):
     return resolve(path, **kwargs)


+def _unavailable(error) -> errors.UserError:
+    return getattr(error, "user_error", None) or errors.embedding_unavailable(
+        str(error) or "the embedding server did not start")
+
+
 class SearchService:
     def __init__(
         self,
@@ -105,12 +111,13 @@ class SearchService:
                 try:
                     self._index_lock = self._probe_lock()
                 except BlockingIOError as error:
-                    raise EmbeddingError("indexing in progress") from error
+                    raise EmbeddingError("indexing in progress",
+                                         user_error=errors.index_running()) from error
             elif self._indexing():
                 self._cancel_idle()
                 await self._stop_locked()
                 await self.state.update(embedder="stopped")
-                raise EmbeddingError("indexing in progress")
+                raise EmbeddingError("indexing in progress", user_error=errors.index_running())
             try:
                 await self.embedder.start(mode)
             except BaseException:
@@ -206,7 +213,7 @@ class SearchService:
             await self._start(mode)
         except (EmbeddingError, OSError) as error:
             await self.state.update(embedder="stopped")
-            return str(error) or "the embedding server did not start"
+            return _unavailable(error)
         await self.state.update(embedder=self.embedder.mode or "stopped")
         if self.embedder.mode is not None:
             self._arm_idle()
@@ -216,18 +223,19 @@ class SearchService:
         from .embedder import EmbeddingError

         if self._warm_task is not None and self._warm_task.done():
-            if reason := self._warm_task.result():
+            if failure := self._warm_task.result():
                 self._warm_task = None
-                raise EmbeddingError(reason)
+                raise EmbeddingError(failure.title, user_error=failure)
         if self.embedder.ready(mode):
             return
         task = self._warming(mode)
         # An already warm server can finish in one turn; a cold load stays in the background.
         await asyncio.sleep(0)
         if not task.done():
-            raise EmbeddingError("the embedding server is starting")
-        if reason := task.result():
-            raise EmbeddingError(reason)
+            raise EmbeddingError("the embedding server is starting",
+                                 user_error=errors.server_starting())
+        if failure := task.result():
+            raise EmbeddingError(failure.title, user_error=failure)

     async def _stop_locked(self):
         stopping = asyncio.create_task(self.embedder.stop())
@@ -320,16 +328,13 @@ class SearchService:
         if message["t"] == "warm":
             try:
                 if indexing:
-                    raise EmbeddingError("indexing in progress")
-                if reason := await asyncio.shield(self._warming("text")):
-                    raise EmbeddingError(reason)
+                    raise EmbeddingError("indexing in progress", user_error=errors.index_running())
+                if failure := await asyncio.shield(self._warming("text")):
+                    raise EmbeddingError(failure.title, user_error=failure)
                 return self.state.message()
             except (EmbeddingError, OSError) as error:
                 await self.state.update(embedder="stopped")
-                return {
-                    "t": "warm_failed",
-                    "reason": str(error) or "the embedding server did not start",
-                }
+                return {"t": "warm_failed", "error": _unavailable(error).to_dict()}
         seq = message.get("seq")
         q, legs = message.get("q"), message.get("legs", ["words", "meaning"])
         limit = message.get("limit", self.settings().max_results)
@@ -346,12 +351,8 @@ class SearchService:
                 or any(not isinstance(kind, str) or kind not in PREFIXES.values()
                        for kind in kinds)))
         ):
-            return {
-                "t": "error",
-                "seq": seq,
-                "code": "bad-request",
-                "reason": "Invalid search arguments",
-            }
+            return {"t": "error", "seq": seq,
+                    **errors.bad_request("Invalid search arguments").to_dict()}
         try:
             self._refresh()
             if not indexing and self._indexing():
@@ -362,23 +363,25 @@ class SearchService:
                 q, legs=["words"] if indexing or unverified else legs, limit=limit, seq=seq,
                 kinds=kinds
             )
+            code = (reply["degraded"] or {}).get("code")
             if unverified:
                 reply["legs"] = ["words"]
-                reply["degraded"] = "embedding model failed verification"
-            elif indexing or reply["degraded"] == "indexing in progress":
+                reply["degraded"] = errors.embedding_unavailable(
+                    "embedding model failed verification").to_dict()
+            elif indexing or code == "index-running":
                 if "words" not in reply["legs"]:
                     reply = await self.searcher.search(q, legs=["words"], limit=limit, seq=seq,
                                                        kinds=kinds)
                 reply["legs"] = ["words"]
-                reply["degraded"] = "indexing in progress"
-            elif reply["degraded"] == "the embedding server is starting":
+                reply["degraded"] = errors.index_running().to_dict()
+            elif code == "server-starting":
                 if "words" not in reply["legs"]:
                     reply = await self.searcher.search(q, legs=["words"], limit=limit, seq=seq,
                                                        kinds=kinds)
                 reply["legs"] = ["words"]
-                reply["degraded"] = "the embedding server is starting"
-        except FileNotFoundError as error:
-            return {"t": "error", "seq": seq, "code": "no-index", "reason": str(error)}
+                reply["degraded"] = errors.server_starting().to_dict()
+        except FileNotFoundError:
+            return {"t": "error", "seq": seq, **errors.no_index().to_dict()}
         return reply

     async def stop(self):
```

- [ ] **Step 7: The socket layer sends objects on every route**

`helper/omafindd/ipc.py`. `_failure` maps a `UserFailure` to its object and anything else to `internal`. `_name` gives the file name for preview and open copy, or "The file" when the id no longer resolves. A missing file is `file-missing`, an offline drive is `drive-not-mounted` named by the item's `label`, and a launch `OSError` is `open_failed` with `open-failed`.

```diff
diff --git a/helper/omafindd/ipc.py b/helper/omafindd/ipc.py
index b9d3dbb..d1825ce 100644
--- a/helper/omafindd/ipc.py
+++ b/helper/omafindd/ipc.py
@@ -11,7 +11,7 @@ from contextlib import closing
 from pathlib import Path
 from threading import Lock

-from . import opener
+from . import errors, opener
 from .state import State

 PROTOCOL_VERSION = 1
@@ -28,6 +28,16 @@ class AlreadyRunning(Exception):
     pass


+def _failure(error) -> errors.UserError:
+    if isinstance(error, errors.UserFailure):
+        return error.error
+    return errors.internal(str(error) or type(error).__name__)
+
+
+def _name(item) -> str:
+    return Path(item["path"]).name if item else "The file"
+
+
 class IpcServer:
     def __init__(self, path: Path, state: State | None = None, *, peer_uid=peer_uid,
                  service=None, setup=None) -> None:
@@ -169,7 +179,7 @@ class IpcServer:
             try:
                 reply = await self.setup.handle(message, client=writer)
             except Exception as error:
-                reply = {"t": "error", "for": message["t"], "reason": str(error)}
+                reply = errors.reply(message["t"], _failure(error))
             try:
                 await self._send(writer, reply)
             except (ConnectionError, OSError):
@@ -184,7 +194,7 @@ class IpcServer:
                 try:
                     reply = await self._overlay(writer, message)
                 except Exception as error:
-                    reply = {"t": "error", "id": message.get("id"), "reason": str(error)}
+                    reply = {"t": "error", "id": message.get("id"), **_failure(error).to_dict()}
                 if pending["latest"] is not token:
                     return
                 if reply["t"] == "preview":
@@ -204,7 +214,7 @@ class IpcServer:
             else:
                 return
         except Exception as error:
-            reply = {"t": "error", "seq": message.get("seq"), "reason": str(error)}
+            reply = {"t": "error", "seq": message.get("seq"), **_failure(error).to_dict()}
             if message["t"] == "open":
                 reply.update({"id": message.get("id"), "for": "open"})
         if reply["t"] == "results":
@@ -233,11 +243,11 @@ class IpcServer:
             from . import preview

             if item is None or (not item.get("offline") and not Path(item["path"]).is_file()):
-                return {"t": "error", "id": item_id, "code": "missing", "reason": "File is missing"}
+                return {"t": "error", "id": item_id, **errors.file_missing(_name(item)).to_dict()}
             query = message.get("q", "")
             if not isinstance(query, str):
-                return {"t": "error", "id": item_id, "code": "bad-request",
-                        "reason": "Invalid preview arguments"}
+                return {"t": "error", "id": item_id,
+                        **errors.bad_request("Invalid preview arguments").to_dict()}
             rendering = asyncio.create_task(asyncio.to_thread(preview.render, item, query))
             try:
                 reply = await asyncio.shield(rendering)
@@ -248,26 +258,23 @@ class IpcServer:
             # A later reply of the same search rebuilds item dicts, so compare the path.
             current = self.resolve(writer, item_id)
             if current is None or current.get("path") != item.get("path"):
-                reply = {"t": "error", "id": item_id, "code": "missing",
-                         "reason": "File is missing"}
+                reply = {"t": "error", "id": item_id, **errors.file_missing(_name(item)).to_dict()}
             return reply
-        if item is None:
-            reason = "missing"
+        if item is None or (not item.get("offline") and not Path(item["path"]).is_file()):
+            failure = errors.file_missing(_name(item))
         elif item.get("offline"):
-            reason = "offline"
-        elif not Path(item["path"]).is_file():
-            reason = "missing"
+            failure = errors.drive_not_mounted(item.get("label") or "The drive")
         else:
-            reason = None
-        if reason:
-            return {"t": "open_failed", "id": item_id, "reason": reason}
+            failure = None
+        if failure:
+            return {"t": "open_failed", "id": item_id, "error": failure.to_dict()}
         how = message.get("how", "open")
         line = message.get("line")
         if how not in ("open", "reveal") or (
             "line" in message and (type(line) is not int or line < 1)
         ):
-            return {"t": "error", "id": item_id, "for": "open", "code": "bad-request",
-                    "reason": "Invalid open arguments"}
+            return {"t": "error", "id": item_id, "for": "open",
+                    **errors.bad_request("Invalid open arguments").to_dict()}
         target = dict(item)
         if target.get("kind") not in ("text", "code"):
             line = None
@@ -276,7 +283,13 @@ class IpcServer:
             target["loc"] = jump
             if target["kind"] == "code":
                 target["open_line"] = jump
-        opener.launch(target, how=how)
+        try:
+            opener.launch(target, how=how)
+        except OSError as error:
+            reason = (f"{error.filename}: {error.strerror}" if error.filename and error.strerror
+                      else str(error) or type(error).__name__)
+            return {"t": "open_failed", "id": item_id,
+                    "error": errors.open_failed(_name(item), reason).to_dict()}
         return {"t": "opened", "id": item_id, **opener.description(target, how=how)}

     def status_message(self):
```

- [ ] **Step 8: `runtime_progress.error` replaces `reason`**

`helper/omafindd/install.py`. No scope raises `build-no-scope`. A failed build keeps today's last stderr line as the cause of `build-failed`, and Task 3 replaces that path with `errors.build_failure(log)`. Download errors become `model-download-failed`, except the download's own checksum mismatch, which becomes `model-verify-failed` for that file. The post-download verify becomes `model-verify-failed`. Anything else is `internal`.

```diff
diff --git a/helper/omafindd/install.py b/helper/omafindd/install.py
index 5a71a02..fb06372 100644
--- a/helper/omafindd/install.py
+++ b/helper/omafindd/install.py
@@ -8,7 +8,7 @@ import time
 from collections import deque
 from pathlib import Path

-from . import models
+from . import errors, models


 class Paused(Exception):
@@ -57,7 +57,7 @@ class RuntimeJob:
             "total": round(sum(f.size for f in models.FILES) / 1e6),
             "unit": "MB",
             "left_seconds": None,
-            "reason": None,
+            "error": None,
             "build": {
                 "state": "wait",
                 "seconds": None,
@@ -133,7 +133,7 @@ class RuntimeJob:
             if self._message["build"]["state"] == "ok" and all(
                 f["state"] == "ok" for f in self._message["files"].values()
             ):
-                self._message.update(state="done", step=None, file=None, reason=None)
+                self._message.update(state="done", step=None, file=None, error=None)
             elif self._message["state"] == "done":
                 self._message.update(state="idle", step=None, file=None)
             return self.snapshot()
@@ -150,7 +150,7 @@ class RuntimeJob:
                 return self.snapshot()
             self._paused = self._stopping = False
             self._samples.clear()
-            self._message.update(state="running", reason=None, left_seconds=None)
+            self._message.update(state="running", error=None, left_seconds=None)
             self._loop = asyncio.get_running_loop()
             self._task = asyncio.create_task(self._launch())
             return self.snapshot()
@@ -176,10 +176,7 @@ class RuntimeJob:
             self._message["build"]["state"] = "ok"
             return
         if not await self._scope_available():
-            raise RuntimeError(
-                "Cannot build safely: the systemd user memory scope is unavailable. "
-                "Run bin/omafind build-runtime in a user session."
-            )
+            raise errors.UserFailure(errors.build_no_scope())
         if self._paused:
             raise Paused
         self._message.update(step="build", file=None)
@@ -216,11 +213,9 @@ class RuntimeJob:
             raise Paused
         if code:
             self._message["build"]["state"] = "failed"
-            last = next((line for line in reversed(lines) if line), f"exit {code}")
-            raise RuntimeError(
-                f"The runtime build failed: {last}. "
-                "Run bin/omafind build-runtime in a terminal for the full log."
-            )
+            last = next((line for line in reversed(lines) if line),
+                        f"The build exited with code {code}")
+            raise errors.UserFailure(errors.build_failed(last))
         self._message["build"].update(state="ok", seconds=round(self.clock() - started))
         await self._push(changed=True)

@@ -262,15 +257,24 @@ class RuntimeJob:
                 raise Paused
             self._message.update(step="download", file=None)
             await self._push(changed=True)
-            await asyncio.to_thread(self.download, self.data_dir / "model", progress=self._progress)
+            try:
+                await asyncio.to_thread(
+                    self.download, self.data_dir / "model", progress=self._progress)
+            except Paused:
+                raise
+            except Exception as error:
+                # models.download names a damaged file only in its message.
+                prefix = "Model sha256 mismatch: "
+                failure = (errors.model_verify_failed(str(error).removeprefix(prefix))
+                           if str(error).startswith(prefix)
+                           else errors.model_download_failed(str(error) or type(error).__name__))
+                raise errors.UserFailure(failure) from error
             if self._paused:
                 raise Paused
             verified = await asyncio.to_thread(self.valid, self.data_dir / "model")
             for key, file in zip(("model", "mmproj"), models.FILES, strict=True):
                 if not verified.get(file.name, False):
-                    raise RuntimeError(
-                        f"Model sha256 mismatch: {file.name}. Press Resume to download it again."
-                    )
+                    raise errors.UserFailure(errors.model_verify_failed(file.name))
                 self._bytes[file.name] = file.size
                 self._message["files"][key].update(state="ok", done=round(file.size / 1e6))
                 await self._push(changed=True)
@@ -280,11 +284,11 @@ class RuntimeJob:
             )
         except Paused:
             self._message.update(state="paused", left_seconds=None)
+        except errors.UserFailure as failure:
+            self._message.update(state="failed", error=failure.error.to_dict(), left_seconds=None)
         except Exception as error:
-            reason = str(error)
-            if reason.startswith("Model sha256 mismatch:") and "Press Resume" not in reason:
-                reason += ". Press Resume to download it again."
-            self._message.update(state="failed", reason=reason, left_seconds=None)
+            failure = errors.internal(str(error) or type(error).__name__)
+            self._message.update(state="failed", error=failure.to_dict(), left_seconds=None)
         await self._push(changed=True)

     def _terminate(self):
```

- [ ] **Step 9: Keep the CLI working with the new shapes**

`bin/omafind`. `omafind search` printed `reply["reason"]`, which would now raise `KeyError`. `omafind discover --json` would show a traceback for `UserFailure`. The `omafindd.errors` import stays inside `discover`, after the venv re-exec, so `test_cli_import_needs_only_stdlib` keeps passing.

```diff
diff --git a/bin/omafind b/bin/omafind
index 0677dad..acb3e4b 100755
--- a/bin/omafind
+++ b/bin/omafind
@@ -335,7 +335,7 @@ def search(args, env, request):
         print("socket silent", file=sys.stderr)
         return 3
     if reply["t"] == "error":
-        print(reply["reason"], file=sys.stderr)
+        print(f'{reply["title"]} {reply["detail"]}'.strip(), file=sys.stderr)
         return 2 if reply.get("code") == "bad-request" else 1
     if parsed.json:
         print(json.dumps(reply, separators=(",", ":"), ensure_ascii=False))
@@ -414,9 +414,13 @@ def discover(args, env, execve=os.execve):
         return execve(str(python), [str(python), str(PLUGIN_ROOT / "bin/omafind"),
                                   "discover", *args], env)
     from omafindd.discovery import snapshot
+    from omafindd.errors import UserFailure

     try:
         body = snapshot(home=Path(env["HOME"]), volume=parsed.volume)
+    except UserFailure as failure:
+        print(f"{failure.error.title} {failure.error.detail}", file=sys.stderr)
+        return 1
     except (OSError, ValueError, subprocess.SubprocessError) as error:
         print(" ".join(str(error).splitlines()), file=sys.stderr)
         return 1
```

- [ ] **Step 10: Run the full checks**

```bash
uv run --project helper pytest -q
node --test "tests/js/*.test.mjs"
uv run --project helper ruff check helper tests bin/omafind scripts evals
scripts/qmllint.sh
git diff --check
```

Expected: all green (integration run: `985 passed`, JS `226` pass). The JS tests do not read daemon replies, so they are unaffected.

- [ ] **Step 11: Commit**

```bash
git add helper/omafindd/errors.py helper/omafindd/embedder.py helper/omafindd/setup.py \
  helper/omafindd/service.py helper/omafindd/search.py helper/omafindd/ipc.py \
  helper/omafindd/diskguard.py helper/omafindd/discovery.py helper/omafindd/install.py \
  bin/omafind \
  tests/helper/test_errors.py tests/helper/test_embedder.py tests/helper/test_discovery.py \
  tests/helper/test_diskguard.py tests/helper/test_ipc_setup.py tests/helper/test_ipc_search.py \
  tests/helper/test_ipc_overlay.py tests/helper/test_ipc_volumes.py tests/helper/test_permissions.py \
  tests/helper/test_install.py tests/helper/test_cli.py
git status --short
git diff --staged --stat
git commit -S -m "fix(omafindd): send every failure as one error object"
```

**Consumers for Task 6/7.** Between this commit and Tasks 6 and 7, the JS and QML below still read the old fields. That is accepted: the daemon and plugin ship together, and these surfaces show an empty or `[object Object]` value until Tasks 6 and 7 land. Listed here only, with no change planned in this task:

- `Service.qml:335-346` `case "error"`: routing by `for`/`seq`/`id` still works. `receiveSetupError` (`:440-456`) reads `message.reason` (now absent), so `discoverError`, `driveError`, `bindsError` and `setupError` become `""`.
- `Service.qml:358-360` `warm_failed`: reads `message.reason` and now gets `""`.
- `Service.qml:390-393` (`discover_children`) and `:491-492` (`receiveCounts`): keep `error` only when it is a string, so object errors are dropped and a failed walk looks finished. This feeds `lib/setup.js:212`, `lib/setup.js:218`, `ui/DriveDialog.qml:41` (`walk.error`), `ui/FolderTree.qml:105-158,227-228` (`cached[path].error`).
- `Service.qml:431-432` → `lib/volumes.js:45-46` (`paused`): reads only `free_gb` and `need_gb`, so it is unaffected. `diskBanner` (`lib/volumes.js:94-98`) keeps its own copy until Task 7.
- `lib/setup.js:126`: `rp.reason` on `runtime_progress` (now `rp.error`), so the step 1 footer falls back to its default hint.
- `ui/PathField.qml:30`: `listing.error` (fs_list) into a `string` property, so it shows `[object Object]`. It does not branch on `missing`, `not-a-directory` or `denied`, so no `reason_code` field is kept.
- `SearchView.qml:49-56,435-453`: `degradedReason` is `String(reply.degraded)` (`[object Object]`), and `degradedClause` regex-matches the old strings. `:444` reads `root.reply.reason` for search errors.
- `lib/results.js:119` and `lib/searchState.js:64`: only test `degraded != null`, so they are unaffected.
- `Overlay.qml:306-310`: `failOpen(message.reason)` on `open_failed` (now `message.error`), and `failOpen("error")` on open `error`.
- `ui/SetupIndex.qml:172`: `problems[].reason`. The daemon still sends it in this task; Task 5 changes it.
- `lib/Update.js:26-59`: reads `bin/omafind setup` output, not daemon replies. Task 3 owns that change.

---

### Task 3: Build preflight, build log, CLI JSON, startup log

**Files:**

- Create: `helper/omafindd/startlog.py`
- Modify: `helper/omafindd/paths.py` (add `logs_dir` between `data_dir` and `runtime_bin`)
- Modify: `helper/omafindd/tools.py` (`BUILD_NEEDS`, `missing_build`, `check(build=, exists=)`)
- Modify: `helper/omafindd/install.py` (imports; `RuntimeJob.__init__`; `_build` as Task 2 left it)
- Modify: `helper/omafindd/__main__.py`, `helper/omafindd/main.py` (start log)
- Modify: `bin/omafind` (`_command`, `setup` split into `_setup` + `setup`; `status`; `build_runtime`; `main` and usage)
- Test: `tests/helper/test_errors.py` (Task 1 file), `tests/helper/test_tools.py`, `tests/helper/test_install.py`, `tests/helper/test_cli.py`, `tests/helper/test_update.py`
- No new build-log fixtures: Task 1's `tests/fixtures/build/missing-header.log`, `cmake-error.log` and `ninja-only.log` already cover the parser, and Task 1's `build_failure` already prefers `fatal error:` over `error:`/`CMake Error` over `FAILED:` and drops a trailing colon. This task does not touch `errors.py`.

**Interfaces:**

- Consumes (Task 1): `errors.UserFailure`, `errors.tools_missing`, `errors.build_missing_packages`, `errors.build_failed`, `errors.helper_install_failed`, `errors.build_no_scope`, `errors.build_failure`, `UserError.to_dict()`. (Task 2): `RuntimeJob._run` turns `UserFailure` into `runtime_progress.state:"failed"` with `error` set to the object; `_build` raises `UserFailure(errors.build_no_scope())` for the scope check.
- Produces:
  - `paths.logs_dir(data: Path | None = None) -> Path`: `<data>/cache/logs`, both directories created 0700 on demand. With no argument it uses `paths.data_dir()`. The installer passes its own `data_dir` so tests with a temporary data directory stay inside it.
  - `tools.BUILD_NEEDS`, `tools.missing_build(*, which=shutil.which, exists=os.path.exists) -> list[str]`, `tools.check(*, which=shutil.which, run=subprocess.run, build=False, exists=os.path.exists) -> list[str]`, exactly as the contract states.
  - `RuntimeJob(..., missing_build=tools.missing_build)`: injectable preflight, called with no arguments. Missing build packages fail the engine step with `build-missing-packages` before the scope check and before any spawn.
  - `<data>/cache/logs/build-runtime.log` (0600, truncated per run, stdout and stderr together). If the log cannot be opened, the build still runs with its output discarded, and a failure is `build-failed` naming the exit code, without `log`.
  - `<data>/cache/logs/omafindd-start.log` (0600, present only while the last start failed).
  - `startlog.NAME = "omafindd-start.log"`, `startlog.write(text)`, `startlog.clear()`. Neither raises.
  - `bin/omafind setup --json`: last stdout line is `{"ok":true,"build_missing":[...]}` or `{"ok":false,"error":{...}}`. Task 6 runs it from `Service.qml`.
  - `bin/omafind setup` fails only on missing runtime tools (`tools-missing`), a failed step or a silent socket (`helper-install-failed`). Missing build packages never fail setup, because `lib/Update.js` runs setup to bring the daemon up to date and must not stop on a package only the engine build needs. While the runtime binary is missing, setup prints `Build packages missing: <list>. The search engine step in setup installs them.` to stderr and lists them in `build_missing`; the engine step's preflight then blocks the build with `build-missing-packages`.
  - `bin/omafind status [--json]`: `tools.missing` includes the build packages while the runtime binary is missing, so status exits 1 and prints the `pacman` line for them.
  - `bin/omafind build-runtime`: stops with exit 1 and the `pacman` line when build packages are missing.

- [ ] **Step 1: Write the failing parser, tools and CLI tests**

`tests/helper/test_errors.py`: one parser case Task 1 does not cover, an unknown missing header.

```diff
diff --git a/tests/helper/test_errors.py b/tests/helper/test_errors.py
index 7166d3c..1ecb119 100644
--- a/tests/helper/test_errors.py
+++ b/tests/helper/test_errors.py
@@ -183,3 +183,11 @@ def test_empty_or_missing_log_reports_the_exit_code(tmp_path):
     empty.write_text("")
     assert errors.build_failure(empty, 2).detail.startswith("The build exited with code 2.")
     assert errors.build_failure(tmp_path / "absent.log", 2).code == "build-failed"
+
+
+def test_build_failure_keeps_an_unknown_missing_header_as_build_failed(tmp_path):
+    log = tmp_path / "build-runtime.log"
+    log.write_text("x.cpp:1:10: fatal error: foo/bar.h: No such file or directory\n")
+    error = errors.build_failure(log, 1)
+    assert error.code == "build-failed"
+    assert error.detail.startswith("x.cpp:1:10: fatal error: foo/bar.h: No such file or directory.")
```

`tests/helper/test_tools.py`: the preflight's packages, one missing package named alone, the `build` flag of `check`, and setup and status behaviour. `fd_ten` is a fake `fd --version`.

```diff
diff --git a/tests/helper/test_tools.py b/tests/helper/test_tools.py
index 82016e9..7ee15d5 100644
--- a/tests/helper/test_tools.py
+++ b/tests/helper/test_tools.py
@@ -1,5 +1,8 @@
+import shutil
 import subprocess

+import pytest
+
 pytest_plugins = ("test_cli",)


@@ -45,3 +48,126 @@ def test_status_json_reports_tools(cli, env, venv, capsys):

     assert cli.main(["status", "--json"], env, run=FakeRun(), probe=lambda *args: True) == 0
     assert json.loads(capsys.readouterr().out)["tools"] == {"missing": []}
+
+
+def fd_ten(argv, **kwargs):
+    return subprocess.CompletedProcess(argv, 0, "fd 10.2.0\n", "")
+
+
+def test_missing_build_lists_every_build_package():
+    from omafindd.tools import missing_build
+
+    assert missing_build(which=lambda name: None, exists=lambda path: False) == [
+        "vulkan-headers", "shaderc", "gcc", "git", "uv"]
+
+
+def test_missing_build_names_only_the_missing_package():
+    from omafindd.tools import missing_build
+
+    assert missing_build(which=lambda name: None if name == "glslc" else "/bin/" + name,
+                         exists=lambda path: True) == ["shaderc"]
+    assert missing_build(which=lambda name: "/bin/" + name,
+                         exists=lambda path: False) == ["vulkan-headers"]
+
+
+def test_check_build_reports_exactly_the_missing_packages(tmp_path):
+    from omafindd.tools import TOOLS, check
+
+    tools = tmp_path / "bin"
+    tools.mkdir()
+    for name in (*TOOLS, "c++"):
+        (tools / name).write_text("#!/bin/sh\n")
+        (tools / name).chmod(0o755)
+    root = tmp_path / "root"
+    probes = {"which": lambda name: shutil.which(name, path=str(tools)),
+              "exists": lambda path: (root / path.lstrip("/")).exists()}
+    assert check(run=fd_ten, **probes) == []
+    assert check(run=fd_ten, build=True, **probes) == ["vulkan-headers", "shaderc", "uv"]
+    header = root / "usr/include/vulkan/vulkan_core.h"
+    header.parent.mkdir(parents=True)
+    header.touch()
+    assert check(run=fd_ten, build=True, **probes) == ["shaderc", "uv"]
+
+
+def test_check_build_lists_a_shared_package_once():
+    from omafindd.tools import check
+
+    assert check(which=lambda name: None if name == "git" else "/bin/" + name, run=fd_ten,
+                 exists=lambda path: True, build=True) == ["git"]
+
+
+def test_setup_json_names_missing_runtime_tools(cli, env, capsys):
+    import json
+
+    assert cli.setup(env, run=fd_ten, which=lambda name: None, as_json=True) == 1
+    output = capsys.readouterr()
+    error = json.loads(output.out.splitlines()[-1])["error"]
+    assert error["code"] == "tools-missing"
+    assert error["fix"]["packages"] == output.err.split()[4:]
+
+
+def test_setup_names_missing_build_packages_and_still_installs(cli, env, monkeypatch, capsys):
+    import json
+
+    from omafindd import tools
+    from test_cli import FakeRun
+
+    monkeypatch.setattr(tools, "missing_build", lambda **kwargs: ["vulkan-headers", "shaderc"])
+    run = FakeRun(active="inactive")
+    assert cli.setup(env, run=run, probe=lambda path, timeout: True,
+                     which=lambda name: "/bin/" + name, as_json=True) == 0
+    output = capsys.readouterr()
+    assert output.err == ("Build packages missing: vulkan-headers, shaderc. "
+                          "The search engine step in setup installs them.\n")
+    assert json.loads(output.out.splitlines()[-1]) == {
+        "ok": True, "build_missing": ["vulkan-headers", "shaderc"]}
+    assert ["systemctl", "--user", "enable", "--now", "omafind.service"] in [
+        command for command, _ in run.calls]
+
+
+def test_setup_skips_build_packages_when_the_runtime_exists(cli, env, monkeypatch, capsys):
+    import json
+
+    from omafindd import paths, tools
+    from test_cli import FakeRun
+
+    def unexpected(**kwargs):
+        raise AssertionError("an installed runtime needs no build packages")
+
+    binary = paths.runtime_bin()
+    binary.parent.mkdir(parents=True)
+    binary.write_text("fake runtime")
+    binary.chmod(0o755)
+    monkeypatch.setattr(tools, "missing_build", unexpected)
+    assert cli.setup(env, run=FakeRun(active="inactive"), probe=lambda path, timeout: True,
+                     which=lambda name: "/bin/" + name, as_json=True) == 0
+    output = capsys.readouterr()
+    assert output.err == ""
+    assert json.loads(output.out.splitlines()[-1]) == {"ok": True, "build_missing": []}
+
+
+@pytest.mark.parametrize("args", [["status"], ["status", "--json"]])
+def test_status_adds_build_packages_while_the_runtime_is_missing(cli, env, venv, monkeypatch,
+                                                                  capsys, args):
+    import json
+
+    from omafindd import tools
+    from test_cli import FakeRun
+
+    monkeypatch.setattr(tools, "missing_build", lambda **kwargs: ["vulkan-headers", "shaderc"])
+    assert cli.main(args, env, run=FakeRun(), probe=lambda *args: True) == 1
+    output = capsys.readouterr()
+    assert output.err.splitlines()[-1] == "sudo pacman -S --needed vulkan-headers shaderc"
+    if "--json" in args:
+        assert json.loads(output.out)["tools"] == {"missing": ["vulkan-headers", "shaderc"]}
+
+
+def test_build_runtime_stops_on_missing_build_packages(cli, env, venv, monkeypatch, capsys):
+    from omafindd import tools
+
+    def run(*args, **kwargs):
+        raise AssertionError("the build must not start")
+
+    monkeypatch.setattr(tools, "missing_build", lambda **kwargs: ["vulkan-headers", "shaderc"])
+    assert cli.main(["build-runtime"], env, run=run) == 1
+    assert capsys.readouterr().err == "sudo pacman -S --needed vulkan-headers shaderc\n"
```

`tests/helper/test_cli.py`: the host decides which build packages exist, so the shared `env` fixture pins the preflight to "nothing missing" and the tests above patch it again. Four `setup --json` tests go before `test_failed_runtime_build_does_not_download`.

```diff
diff --git a/tests/helper/test_cli.py b/tests/helper/test_cli.py
index 67224fa..fe6ba9d 100644
--- a/tests/helper/test_cli.py
+++ b/tests/helper/test_cli.py
@@ -25,6 +25,10 @@ def cli():

 @pytest.fixture
 def env(tmp_path, monkeypatch):
+    from omafindd import tools
+
+    # Build packages differ per host; tests that check them patch missing_build again.
+    monkeypatch.setattr(tools, "missing_build", lambda **kwargs: [])
     values = {"HOME": str(tmp_path / "home"), "XDG_CONFIG_HOME": str(tmp_path / "config"),
               "XDG_DATA_HOME": str(tmp_path / "data"), "XDG_RUNTIME_DIR": str(tmp_path / "run")}
     for key, value in values.items():
@@ -296,6 +300,51 @@ def test_setup_socket_timeout_reports_journal(cli, env, capsys):
     assert "socket silent" in capsys.readouterr().err


+def test_setup_json_ends_with_ok(cli, env, capsys):
+    assert cli.main(["setup", "--json"], env, run=FakeRun(active="inactive"),
+                    probe=lambda path, timeout: True) == 0
+    lines = capsys.readouterr().out.splitlines()
+    assert lines[:2] == ["unit active", "socket answering"]
+    assert json.loads(lines[-1]) == {"ok": True, "build_missing": []}
+
+
+def test_setup_json_carries_the_failed_step_output(cli, env, capsys):
+    def run(command, **kwargs):
+        if command == ["fd", "--version"]:
+            return subprocess.CompletedProcess(command, 0, "fd 10.5.0\n", "")
+        return subprocess.CompletedProcess(command, int(command[0] == "uv"), "",
+                                           "error: no network\n")
+
+    assert cli.main(["setup", "--json"], env, run=run) == 1
+    error = json.loads(capsys.readouterr().out.splitlines()[-1])["error"]
+    assert error["code"] == "helper-install-failed"
+    assert error["detail"].startswith("error: no network. ")
+    assert error["fix"] == {"kind": "retry"}
+
+
+def test_setup_json_reports_a_silent_socket(cli, env, capsys):
+    now = [0.0]
+
+    def sleep(seconds):
+        now[0] += seconds
+
+    assert cli.setup(env, run=FakeRun(active="inactive"), probe=lambda path, timeout: False,
+                     clock=lambda: now[0], sleep=sleep, as_json=True) == 1
+    error = json.loads(capsys.readouterr().out.splitlines()[-1])["error"]
+    assert error["code"] == "helper-install-failed"
+    assert error["detail"].startswith("The omafind service did not answer on its socket. ")
+
+
+def test_setup_json_reports_an_os_error_as_the_last_line(cli, env, capsys):
+    del env["XDG_RUNTIME_DIR"]
+    assert cli.main(["setup", "--json"], env, run=FakeRun()) == 1
+    output = capsys.readouterr()
+    assert "XDG_RUNTIME_DIR is unset" in output.err
+    error = json.loads(output.out.splitlines()[-1])["error"]
+    assert error["code"] == "helper-install-failed"
+    assert error["detail"].startswith("XDG_RUNTIME_DIR is unset")
+
+
 def test_failed_runtime_build_does_not_download(cli, env):
     python = Path(env["HOME"]) / ".local/share/omafind/venv/bin/python"
     python.parent.mkdir(parents=True)
```

- [ ] **Step 2: Write the failing installer tests**

`tests/helper/test_install.py`: `job_factory` gains a `missing_build` keyword whose default finds nothing missing, so the existing tests do not depend on the host's packages. Task 2's `test_build_failure_reports_last_stderr_line` goes: the build no longer reads stderr, so that cause cannot exist.

```diff
diff --git a/tests/helper/test_install.py b/tests/helper/test_install.py
index 5a6e9b0..fbcb99c 100644
--- a/tests/helper/test_install.py
+++ b/tests/helper/test_install.py
@@ -1,11 +1,14 @@
 import asyncio
 import os
+from pathlib import Path
 from types import SimpleNamespace

 import pytest
 from omafindd import errors, models
 from omafindd.install import RuntimeJob, gpu_name

+BUILD_LOGS = Path(__file__).resolve().parents[1] / "fixtures/build"
+

 class Process:
     def __init__(self, code=0, stderr=b"", waiting=False):
@@ -44,7 +47,8 @@ def job_factory(tmp_path, monkeypatch):
     monkeypatch.setattr("omafindd.install.shutil.which", lambda name: "/usr/bin/" + name)
     jobs = []

-    def make(*, process=None, valid=None, download=None, clock=lambda: 10.0):
+    def make(*, process=None, valid=None, download=None, clock=lambda: 10.0,
+             missing_build=lambda: []):
         messages, calls = [], []

         async def broadcast(message):
@@ -68,6 +72,7 @@ def job_factory(tmp_path, monkeypatch):
             valid=valid or (lambda directory: {f.name: True for f in models.FILES}),
             gpu=lambda: "RTX 3060 12 GB",
             clock=clock,
+            missing_build=missing_build,
         )
         jobs.append(job)
         return job, messages, calls
@@ -150,13 +155,79 @@ async def test_pause_during_download_stops_at_next_chunk_and_resume_continues(jo
     assert job.snapshot()["state"] == "done"


-async def test_build_failure_reports_last_stderr_line(job_factory):
-    job, _, _ = job_factory(process=Process(1, b"first\nlast error\n"))
+async def test_silent_build_failure_reports_its_exit_code_and_log(job_factory, tmp_path):
+    job, _, _ = job_factory(process=Process(3))
     assert job.snapshot()["error"] is None and "reason" not in job.snapshot()
     await job.start()
     await finish(job)
-    assert job.snapshot()["build"]["state"] == "failed"
-    assert job.snapshot()["error"] == errors.build_failed("last error").to_dict()
+    result = job.snapshot()
+    assert result["build"]["state"] == "failed"
+    assert result["error"]["code"] == "build-failed"
+    assert result["error"]["detail"].startswith("The build exited with code 3. ")
+    assert result["error"]["log"] == str(tmp_path / "cache/logs/build-runtime.log")
+
+
+async def test_build_runs_without_a_log_and_fails_without_one(job_factory, monkeypatch):
+    from omafindd import paths
+
+    def denied(data=None):
+        raise PermissionError(13, "Permission denied")
+
+    monkeypatch.setattr(paths, "logs_dir", denied)
+    job, _, calls = job_factory(process=Process(3))
+    await job.start()
+    await finish(job)
+    result = job.snapshot()
+    assert any(args[0].endswith("scripts/build-runtime.sh") for args, _ in calls)
+    assert result["state"] == "failed"
+    assert result["error"]["code"] == "build-failed"
+    assert result["error"]["detail"].startswith("The build exited with code 3. ")
+    assert "log" not in result["error"]
+
+
+async def test_missing_build_packages_fail_before_the_build_starts(job_factory, tmp_path):
+    job, _, calls = job_factory(missing_build=lambda: ["vulkan-headers", "shaderc"])
+    await job.start()
+    await finish(job)
+    result = job.snapshot()
+    assert result["state"] == "failed"
+    assert result["build"]["state"] == "failed"
+    assert result["error"]["code"] == "build-missing-packages"
+    assert result["error"]["fix"] == {"kind": "install", "packages": ["vulkan-headers", "shaderc"]}
+    assert "log" not in result["error"]
+    assert not calls
+    assert not (tmp_path / "cache/logs/build-runtime.log").exists()
+
+
+async def test_failing_build_script_writes_both_streams_to_a_fresh_log(job_factory, tmp_path):
+    script = tmp_path / "plugin/scripts/build-runtime.sh"
+    script.parent.mkdir(parents=True)
+    script.write_text(f"#!/bin/sh\ncat '{BUILD_LOGS / 'missing-header.log'}'\n"
+                      "echo 'stderr reaches the log' >&2\nexit 1\n")
+    script.chmod(0o755)
+    log = tmp_path / "cache/logs/build-runtime.log"
+    log.parent.mkdir(parents=True)
+    log.write_text("previous run\n")
+    job, _, _ = job_factory()
+
+    async def spawn(*args, **kw):
+        if args[0] == "systemctl":
+            return Process()
+        return await asyncio.create_subprocess_exec(*args, **kw)
+
+    job.spawn = spawn
+    await job.start()
+    await finish(job)
+    text = log.read_text()
+    assert "previous run" not in text
+    assert "fatal error: vulkan/vulkan_core.h" in text
+    assert text.endswith("stderr reaches the log\n")
+    assert log.stat().st_mode & 0o777 == 0o600
+    result = job.snapshot()
+    assert result["build"]["state"] == "failed"
+    assert result["error"]["code"] == "build-missing-packages"
+    assert result["error"]["fix"] == {"kind": "install", "packages": ["vulkan-headers"]}
+    assert result["error"]["log"] == str(log)


 async def test_digest_mismatch_fails_with_model_verify_failed(job_factory):
```

`test_failing_build_script_writes_both_streams_to_a_fresh_log` runs a four-line shell script, not the real build. It checks the real file redirection, the truncation, the 0600 mode and the classification end to end. `test_build_runs_without_a_log_and_fails_without_one` makes `paths.logs_dir` raise: the build still spawns and nothing escapes `_run`.

- [ ] **Step 3: Write the failing start log tests**

`tests/helper/test_update.py`:

```diff
diff --git a/tests/helper/test_update.py b/tests/helper/test_update.py
index 0497d70..0e4a263 100644
--- a/tests/helper/test_update.py
+++ b/tests/helper/test_update.py
@@ -65,6 +65,10 @@ def test_missing_dependency_start_names_module_and_setup(tmp_path):
     assert result.returncode == 1
     assert result.stderr.strip().splitlines() == [
         "omafindd cannot import inotify_simple. Run bin/omafind setup."]
+    log = tmp_path / ".local/share/omafind/cache/logs/omafindd-start.log"
+    assert log.read_text().endswith(
+        " omafindd cannot import inotify_simple. Run bin/omafind setup.\n")
+    assert log.stat().st_mode & 0o777 == 0o600


 def test_fingerprint_rejects_manifest_without_version(plugin):
@@ -96,3 +100,61 @@ async def test_daemon_reports_empty_build_when_fingerprint_fails(tmp_path, monke
         await main._serve(manifest)
     assert started == [""]
     assert "Cannot fingerprint" in caplog.text
+
+
+def test_fatal_start_error_writes_the_start_log(tmp_path, monkeypatch):
+    from omafindd import main, paths, startlog
+
+    async def bind_fails():
+        raise OSError(98, "Address already in use")
+
+    monkeypatch.setenv("HOME", str(tmp_path))
+    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
+    monkeypatch.setattr(main, "_serve", bind_fails)
+    assert main.run() == 1
+    assert "Address already in use" in (paths.logs_dir() / startlog.NAME).read_text()
+
+
+def test_start_log_write_never_raises(tmp_path, monkeypatch):
+    from omafindd import startlog
+
+    (tmp_path / "file").touch()
+    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "file"))
+    startlog.write("bind failed")
+    startlog.clear()
+
+
+async def test_started_daemon_removes_the_start_log(tmp_path, monkeypatch):
+    from omafindd import main, paths, startlog
+
+    class Server:
+        def __init__(self, path, state):
+            self.state = state
+
+        async def start(self):
+            assert stale.exists()
+
+        async def stop(self):
+            pass
+
+        async def broadcast(self, message):
+            pass
+
+    def stop_here():
+        raise main.AlreadyRunning("stop here")
+
+    class Freshness(main._Freshness):
+        def __init__(self, *args):
+            super().__init__(*args)
+            self.volumes.snapshot = stop_here
+
+    monkeypatch.setenv("HOME", str(tmp_path))
+    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
+    monkeypatch.setattr(main, "IpcServer", Server)
+    monkeypatch.setattr(main, "_Freshness", Freshness)
+    stale = paths.logs_dir() / startlog.NAME
+    stale.write_text("old failure\n")
+    manifest = tmp_path / "manifest.json"
+    manifest.touch()
+    assert await main._serve(manifest) == 1
+    assert not stale.exists()
```

`stop_here` ends `_serve` through its `AlreadyRunning` branch right after the server started, so the test proves the log goes away only once the socket is up.

- [ ] **Step 4: Run them to see them fail**

```bash
uv run --project helper pytest -q tests/helper/test_errors.py tests/helper/test_tools.py tests/helper/test_cli.py tests/helper/test_install.py tests/helper/test_update.py
```

Expected:
- `test_build_failure_keeps_an_unknown_missing_header_as_build_failed` passes already (Task 1's parser); it guards the header table.
- Every test that uses `env` errors in setup with `AttributeError: <module 'omafindd.tools'> has no attribute 'missing_build'`.
- `test_check_build_*` fail with `TypeError: check() got an unexpected keyword argument`.
- Every `job_factory` test fails with `TypeError: RuntimeJob.__init__() got an unexpected keyword argument 'missing_build'`.
- The start log tests fail with `ImportError: cannot import name 'startlog'` or `FileNotFoundError` for `omafindd-start.log`.

- [ ] **Step 5: Add `logs_dir` to `helper/omafindd/paths.py`**

```diff
diff --git a/helper/omafindd/paths.py b/helper/omafindd/paths.py
index a284840..0684a9b 100644
--- a/helper/omafindd/paths.py
+++ b/helper/omafindd/paths.py
@@ -34,6 +34,14 @@ def data_dir() -> Path:
     return path


+def logs_dir(data: Path | None = None) -> Path:
+    """`<data>/cache/logs`, created 0700 on demand. `data` defaults to the user's data directory."""
+    cache = (data_dir() if data is None else data) / "cache"
+    cache.mkdir(parents=True, mode=0o700, exist_ok=True)
+    (cache / "logs").mkdir(mode=0o700, exist_ok=True)
+    return cache / "logs"
+
+
 def runtime_bin() -> Path:
     return data_dir_path() / "runtime/bin/llama-server"

```

`permissions.check` expects every directory under the data directory to be 0700. `build-runtime.sh` creates `cache` with `mkdir -p` (0755), and `fix_dirs` corrects it at the next daemon start, as it already does today.

- [ ] **Step 6: Add the build preflight to `helper/omafindd/tools.py`**

```diff
diff --git a/helper/omafindd/tools.py b/helper/omafindd/tools.py
index 4212ae6..1313023 100644
--- a/helper/omafindd/tools.py
+++ b/helper/omafindd/tools.py
@@ -1,3 +1,4 @@
+import os
 import re
 import shutil
 import subprocess
@@ -16,16 +17,35 @@ TOOLS = {
     "tesseract": "tesseract",
 }

+# cmake, ninja and spirv-headers stay out: scripts/build-runtime.sh falls back to private copies.
+BUILD_NEEDS = [
+    ("header", "/usr/include/vulkan/vulkan_core.h", "vulkan-headers"),
+    ("command", "glslc", "shaderc"),
+    ("command", "c++", "gcc"),
+    ("command", "git", "git"),
+    ("command", "uv", "uv"),
+]
+

 def missing_tools(which=shutil.which) -> list[str]:
     return list(dict.fromkeys(package for tool, package in TOOLS.items() if not which(tool)))


-def check(*, which=shutil.which, run=subprocess.run) -> list[str]:
+def missing_build(*, which=shutil.which, exists=os.path.exists) -> list[str]:
+    found = {"header": exists, "command": which}
+    return list(dict.fromkeys(
+        package for kind, target, package in BUILD_NEEDS if not found[kind](target)))
+
+
+def check(*, which=shutil.which, run=subprocess.run, build=False,
+          exists=os.path.exists) -> list[str]:
     missing = missing_tools(which)
     if "fd" not in missing:
         result = run(["fd", "--version"], capture_output=True, text=True)
         version = re.search(r"\bfd\s+(\d+)", result.stdout)
         if result.returncode or version is None or int(version[1]) < 10:
             missing.insert(0, "fd")
+    if build:
+        missing += [package for package in missing_build(which=which, exists=exists)
+                    if package not in missing]
     return missing
```

`check` calls `missing_build` through the module global, so the `env` fixture's patch reaches `setup` and `status`.

- [ ] **Step 7: Preflight and log the build in `helper/omafindd/install.py`**

```diff
diff --git a/helper/omafindd/install.py b/helper/omafindd/install.py
index fb06372..b5235b8 100644
--- a/helper/omafindd/install.py
+++ b/helper/omafindd/install.py
@@ -8,7 +8,7 @@ import time
 from collections import deque
 from pathlib import Path

-from . import errors, models
+from . import errors, models, paths, tools


 class Paused(Exception):
@@ -44,8 +44,10 @@ class RuntimeJob:
         valid=models.verify,
         gpu=gpu_name,
         clock=time.monotonic,
+        missing_build=tools.missing_build,
     ):
         self.data_dir, self.plugin_root = data_dir, plugin_root
+        self.missing_build = missing_build
         self.broadcast, self.spawn = broadcast, spawn
         self.download, self.valid, self.gpu, self.clock = download, valid, gpu, clock
         self._message = {
@@ -175,6 +177,9 @@ class RuntimeJob:
         if self._runtime_exists() or self._message["build"]["state"] == "ok":
             self._message["build"]["state"] = "ok"
             return
+        if missing := self.missing_build():
+            self._message["build"]["state"] = "failed"
+            raise errors.UserFailure(errors.build_missing_packages(missing))
         if not await self._scope_available():
             raise errors.UserFailure(errors.build_no_scope())
         if self._paused:
@@ -185,23 +190,24 @@ class RuntimeJob:
         started = self.clock()
         env = {**os.environ, "OMAFIND_DATA_DIR": str(self.data_dir)}
         env.pop("OMAFIND_BUILD_SCOPED", None)
-        self._process = await self.spawn(
-            str(self.plugin_root / "scripts/build-runtime.sh"),
-            env=env,
-            stdout=asyncio.subprocess.DEVNULL,
-            stderr=asyncio.subprocess.PIPE,
-            start_new_session=True,
-        )
+        try:
+            log = paths.logs_dir(self.data_dir) / "build-runtime.log"
+            descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
+            os.fchmod(descriptor, 0o600)
+        except OSError:
+            # Without a log the build still runs, and a failure names only its exit code.
+            log, descriptor = None, os.open(os.devnull, os.O_WRONLY)
+        with os.fdopen(descriptor, "wb") as stream:
+            self._process = await self.spawn(
+                str(self.plugin_root / "scripts/build-runtime.sh"),
+                env=env,
+                stdout=stream,
+                stderr=asyncio.subprocess.STDOUT,
+                start_new_session=True,
+            )
         if self._paused:
             self._terminate()
-        lines = deque(maxlen=20)
-
-        async def finish():
-            while line := await self._process.stderr.readline():
-                lines.append(line.decode(errors="replace").strip())
-            return await self._process.wait()
-
-        finishing = asyncio.create_task(finish())
+        finishing = asyncio.create_task(self._process.wait())
         while not finishing.done():
             await asyncio.wait({finishing}, timeout=0.5)
             if not finishing.done():
@@ -213,9 +219,9 @@ class RuntimeJob:
             raise Paused
         if code:
             self._message["build"]["state"] = "failed"
-            last = next((line for line in reversed(lines) if line),
-                        f"The build exited with code {code}")
-            raise errors.UserFailure(errors.build_failed(last))
+            if log is None:
+                raise errors.UserFailure(errors.build_failed(f"The build exited with code {code}"))
+            raise errors.UserFailure(await asyncio.to_thread(errors.build_failure, log, code))
         self._message["build"].update(state="ok", seconds=round(self.clock() - started))
         await self._push(changed=True)

```

The child keeps its own copy of the descriptor, so closing it right after the spawn is safe, and the parent holds no file open for the whole build. `deque` is still used by `self._samples`, so its import stays.

- [ ] **Step 8: Write the start log**

Create `helper/omafindd/startlog.py`:

```python
"""The last fatal daemon start failure, kept so the UI can offer "Open log" while it is down."""

import os
import time

from . import paths

NAME = "omafindd-start.log"


def write(text: str) -> None:
    """Replace the start log with `text`. Never raises: it runs while the daemon is failing."""
    try:
        path = paths.logs_dir() / NAME
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text.rstrip()}\n")
    except OSError:
        pass


def clear() -> None:
    try:
        (paths.logs_dir() / NAME).unlink(missing_ok=True)
    except OSError:
        pass
```

`helper/omafindd/__main__.py` loads `startlog` first. It imports only the standard library and `paths`, so it loads even when the venv lacks a dependency:

```diff
diff --git a/helper/omafindd/__main__.py b/helper/omafindd/__main__.py
index da2195a..f05692f 100644
--- a/helper/omafindd/__main__.py
+++ b/helper/omafindd/__main__.py
@@ -1,4 +1,7 @@
 import sys
+import traceback
+
+from . import startlog

 try:
     from .main import run
@@ -8,6 +11,11 @@ except ModuleNotFoundError as error:
     # A venv synced before uv.lock gained a dependency fails here, or at a lazy import inside
     # run(), until setup syncs it.
     package = (error.name or "a dependency").partition(".")[0]
-    print(f"omafindd cannot import {package}. Run bin/omafind setup.", file=sys.stderr)
+    message = f"omafindd cannot import {package}. Run bin/omafind setup."
+    print(message, file=sys.stderr)
+    startlog.write(message)
     code = 1
+except Exception:
+    startlog.write(traceback.format_exc())
+    raise
 raise SystemExit(code)
```

`helper/omafindd/main.py`:

```diff
diff --git a/helper/omafindd/main.py b/helper/omafindd/main.py
index 5433ef7..4931b4e 100644
--- a/helper/omafindd/main.py
+++ b/helper/omafindd/main.py
@@ -9,7 +9,7 @@ import time
 from contextlib import closing
 from pathlib import Path

-from . import build, health, paths, permissions, recovery
+from . import build, health, paths, permissions, recovery, startlog
 from .diskguard import DiskGuard
 from .install import RuntimeJob
 from .ipc import AlreadyRunning, IpcServer
@@ -451,6 +451,7 @@ async def _serve(manifest: Path | None = None, *, interval: float = 0.5) -> int:
     clean = False
     try:
         await server.start()
+        startlog.clear()
         try:
             await asyncio.to_thread(freshness.volumes.snapshot)
         except (OSError, ValueError, subprocess.SubprocessError):
@@ -509,6 +510,7 @@ def run() -> int:
         return asyncio.run(_serve())
     except (OSError, ValueError) as error:
         logger.error('%s', error)
+        startlog.write(str(error))
         return 1
     except KeyboardInterrupt:
         return 0
```

`AlreadyRunning` still returns 1 without a start log: another daemon answers on the socket, so the UI is not offline.

- [ ] **Step 9: Update `bin/omafind`**

```diff
diff --git a/bin/omafind b/bin/omafind
index acb3e4b..8ee8837 100755
--- a/bin/omafind
+++ b/bin/omafind
@@ -166,29 +166,37 @@ def _print_presence(details):


 def _command(command, env, run):
+    """Run one setup step. Returns its failure output, or None when it succeeded."""
     result = run(command, env=env, capture_output=True, text=True)
     if result.returncode:
-        print(result.stderr or result.stdout or f"{command[0]} failed", file=sys.stderr)
-    return result.returncode == 0
+        reason = result.stderr or result.stdout or f"{command[0]} failed"
+        print(reason, file=sys.stderr)
+        return reason
+    return None


-def setup(env, run=subprocess.run, probe=read_hello, clock=time.monotonic, sleep=time.sleep,
-          which=shutil.which):
-    from omafindd.tools import check
+def _setup(env, run, probe, clock, sleep, which):
+    """Returns (error, build packages still missing). Only runtime tools stop setup."""
+    from omafindd import errors, tools

-    missing = check(which=which, run=run)
+    missing = tools.check(which=which, run=run)
     if missing:
         print("sudo pacman -S --needed " + " ".join(missing), file=sys.stderr)
-        return 1
+        return errors.tools_missing(missing), []
+    # The search engine step checks these again before it builds, so setup only names them.
+    build_missing = [] if _presence(env)["runtime"]["present"] else tools.missing_build(which=which)
+    if build_missing:
+        print(f"Build packages missing: {', '.join(build_missing)}. "
+              "The search engine step in setup installs them.", file=sys.stderr)
     home = Path(env["HOME"])
     socket_path = _socket_path(env)
-    if not _command(["systemctl", "--user", "show-environment"], env, run):
-        return 1
+    if failed := _command(["systemctl", "--user", "show-environment"], env, run):
+        return errors.helper_install_failed(failed), build_missing
     python = home / ".local/share/omafind/venv/bin/python"
     sync_env = dict(env, UV_PROJECT_ENVIRONMENT=str(python.parent.parent))
     sync = ["uv", "sync", "--project", str(PLUGIN_ROOT / "helper"), "--frozen", "--no-dev"]
-    if not _command(sync, sync_env, run):
-        return 1
+    if failed := _command(sync, sync_env, run):
+        return errors.helper_install_failed(failed), build_missing
     paths.data_dir()
     python.parent.parent.parent.chmod(0o700)
     config = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
@@ -196,15 +204,16 @@ def setup(env, run=subprocess.run, probe=read_hello, clock=time.monotonic, sleep
     unit.parent.mkdir(parents=True, exist_ok=True)
     shutil.copyfile(PLUGIN_ROOT / "systemd/omafind.service", unit)
     unit.chmod(0o644)
-    if not _command(["systemctl", "--user", "daemon-reload"], env, run):
-        return 1
+    if failed := _command(["systemctl", "--user", "daemon-reload"], env, run):
+        return errors.helper_install_failed(failed), build_missing
     active = run(["systemctl", "--user", "is-active", "omafind.service"],
                  env=env, capture_output=True, text=True)
-    if not _command(["systemctl", "--user", "enable", "--now", "omafind.service"], env, run):
-        return 1
+    if failed := _command(["systemctl", "--user", "enable", "--now", "omafind.service"], env, run):
+        return errors.helper_install_failed(failed), build_missing
     if (active.returncode == 0 and active.stdout.strip() == "active"
-            and not _command(["systemctl", "--user", "restart", "omafind.service"], env, run)):
-        return 1
+            and (failed := _command(["systemctl", "--user", "restart", "omafind.service"],
+                                    env, run))):
+        return errors.helper_install_failed(failed), build_missing
     deadline = clock() + 5
     while clock() < deadline:
         if probe(socket_path, min(0.2, max(0.001, deadline - clock()))):
@@ -214,19 +223,39 @@ def setup(env, run=subprocess.run, probe=read_hello, clock=time.monotonic, sleep
             _print_presence(details)
             if not details["runtime"]["present"] or not all(details["model"]["files"].values()):
                 print("next bin/omafind build-runtime")
-            return 0
+            return None, build_missing
         sleep(min(0.1, max(0, deadline - clock())))
     print("socket silent", file=sys.stderr)
     journal = run(["journalctl", "--user", "-u", "omafind.service", "-n", "20", "--no-pager"],
                   env=env, capture_output=True, text=True)
     print(journal.stdout or journal.stderr, end="", file=sys.stderr)
-    return 1
+    silent = errors.helper_install_failed("The omafind service did not answer on its socket")
+    return silent, build_missing
+
+
+def setup(env, run=subprocess.run, probe=read_hello, clock=time.monotonic, sleep=time.sleep,
+          which=shutil.which, as_json=False):
+    """With `as_json`, the last stdout line is {"ok":true,"build_missing":[...]} or
+    {"ok":false,"error":{...}}."""
+    from omafindd import errors
+
+    try:
+        failure, build_missing = _setup(env, run, probe, clock, sleep, which)
+    except (OSError, ValueError) as error:
+        print(str(error), file=sys.stderr)
+        failure = errors.helper_install_failed(str(error))
+    if as_json:
+        body = ({"ok": True, "build_missing": build_missing} if failure is None
+                else {"ok": False, "error": failure.to_dict()})
+        print(json.dumps(body, separators=(",", ":")))
+    return 0 if failure is None else 1


 def status(env, run=subprocess.run, probe=read_hello, as_json=False):
     from omafindd.tools import check

-    missing = check(run=run)
+    presence = _presence(env)
+    missing = check(run=run, build=not presence["runtime"]["present"])
     enabled_result = run(["systemctl", "--user", "is-enabled", "omafind.service"],
                          env=env, capture_output=True, text=True)
     active_result = run(["systemctl", "--user", "is-active", "omafind.service"],
@@ -239,7 +268,7 @@ def status(env, run=subprocess.run, probe=read_hello, as_json=False):
     answers = bool(probe(path, 0.2))
     details = {"unit": {"enabled": enabled, "active": active},
                "socket": {"path": str(path), "answers": answers},
-               "tools": {"missing": missing}, "venv": _venv(env, run), **_presence(env)}
+               "tools": {"missing": missing}, "venv": _venv(env, run), **presence}
     index = _index_status(env, run)
     details["model"]["verified"] = index.pop("verified")
     details.update(index)
@@ -275,6 +304,11 @@ def status(env, run=subprocess.run, probe=read_hello, as_json=False):


 def build_runtime(env, run=subprocess.run, execve=os.execve):
+    from omafindd import tools
+
+    if missing := tools.missing_build():
+        print("sudo pacman -S --needed " + " ".join(missing), file=sys.stderr)
+        return 1
     python = Path(env["HOME"]) / ".local/share/omafind/venv/bin/python"
     if not python.is_file():
         print("venv missing\nnext bin/omafind setup", file=sys.stderr)
@@ -500,8 +534,8 @@ def main(args=None, env=None, run=subprocess.run, probe=read_hello, request=requ
             return discover(args[1:], env, execve)
         if args and args[0] == "reindex":
             return reindex(args[1:], env, execve)
-        if args == ["setup"]:
-            return setup(env, run, probe)
+        if args in (["setup"], ["setup", "--json"]):
+            return setup(env, run, probe, as_json="--json" in args)
         if args == ["build-runtime"]:
             return build_runtime(env, run, execve)
         if args == ["fingerprint"]:
@@ -512,7 +546,7 @@ def main(args=None, env=None, run=subprocess.run, probe=read_hello, request=requ
     except (OSError, ValueError) as error:
         print(str(error), file=sys.stderr)
         return 1
-    print("Usage: omafind setup | status [--json] | fingerprint | build-runtime | "
+    print("Usage: omafind setup [--json] | status [--json] | fingerprint | build-runtime | "
           "search [--json] [--limit N] QUERY | "
           "reindex [--root PATH]... [--volume UUID] [--incremental] | "
           "discover --json [--volume UUID] | "
```

`git` is both a runtime tool and a build package; `setup` checks only runtime tools, so a missing `git` is `tools-missing`. `setup` catches `OSError` and `ValueError` itself because `main` would otherwise print them without the JSON line. The note line about build packages goes to stderr; the current `Service.qml` (`helperSetup`) shows stderr only until a successful exit clears it, and Task 6 moves it to `--json`.

- [ ] **Step 10: Run the new tests**

```bash
uv run --project helper pytest -q tests/helper/test_errors.py tests/helper/test_tools.py tests/helper/test_cli.py tests/helper/test_install.py tests/helper/test_update.py
```

Expected: all pass. `test_failing_build_script_writes_both_streams_to_a_fresh_log` starts one `/bin/sh` child. It is not a heavy job and needs no memory cap. Never run `scripts/build-runtime.sh` for this task.

- [ ] **Step 11: Run the full checks**

```bash
uv run --project helper pytest -q
node --test "tests/js/*.test.mjs"
uv run --project helper ruff check helper tests bin/omafind scripts evals
scripts/qmllint.sh
git diff --check
```

Expected: all pass (integration run: `1006 passed`, JS `226` pass). Read each output before committing. `pgrep -x llama-server` stays empty, since this task starts no server.

- [ ] **Step 12: Commit**

```bash
git add helper/omafindd/paths.py helper/omafindd/tools.py \
  helper/omafindd/install.py helper/omafindd/startlog.py helper/omafindd/__main__.py \
  helper/omafindd/main.py bin/omafind \
  tests/helper/test_errors.py tests/helper/test_tools.py tests/helper/test_install.py \
  tests/helper/test_cli.py tests/helper/test_update.py
git status --short
git diff --staged --stat
git commit -S -m "fix(omafindd): check build packages and keep the full build log"
```

---

### Task 4: Keep the embedding server log and the start cause

Task 2 already added `EmbeddingError(*args, user_error=None)` and carries `error.user_error` to `warm_failed.error` and `results.degraded`. This task does not touch the class; it only sets `user_error` on start failures.

Line numbers below are measured after Tasks 1-3.

**Files:**
- Modify: `helper/omafindd/embedder.py`
  - imports, lines 4-5 and 19 (add `import re` and `from omafindd import errors`);
  - after `REQUEST_SLOTS = 2` (line 146): add `SERVER_LOG`, `_LOG_CAUSE`, `_open_log`, `_log_cause`, `_attempt_cause` and `_start_cause`;
  - `Embedder.start` device loop, lines 212-236: send the log to the child, collect a cause per attempt and raise with `user_error`;
  - `Embedder._wait_ready`, lines 255-257: raise cause clauses.
- Modify: `tests/helper/test_embedder.py`
  - imports, lines 1-25;
  - new autouse fixture, fake binary and key after line 34;
  - `test_known_vram_start_failure_does_not_retry`, lines 393-399;
  - five new tests appended after line 630 (the end of the file after Task 2).
- No change to `tests/fakes/llama_server.py`. `FakeLlamaServer` runs in-process and never writes to the `stdout` it is given, so it cannot show what reaches the log. The new tests use a small real child process (a Python script written to `tmp_path`) instead. No real `llama-server` starts.

**Interfaces:**
- Consumes:
  - `errors.server_start_failed(reason, log=None)` (Task 1);
  - `paths.logs_dir()` → `<data>/cache/logs`, created on demand (Task 3);
  - `EmbeddingError(message, user_error=...)` (Task 2).
- Produces:
  - Every start failure of a spawned server raises `EmbeddingError("Embedding server failed to start", user_error=errors.server_start_failed(cause, log_path))`. The message text is unchanged, so callers matching on it keep working.
  - `cause` has one of these forms:
    - `It did not answer within 60 s` (the timeout is `startup_timeout` formatted with `:g`, so the 60.0 default reads `60` and a test's 0.2 reads `0.2`; rounding would print `0 s` in tests);
    - `It exited with code 1`;
    - `It was stopped by signal 9` (negative return code, such as an OOM kill);
    - `It could not be started (No such file or directory)` (an `OSError` from the spawn, such as a missing binary).
  - Each form gets ` (<last log line matching error|failed|no devices, case-insensitive, trailing period dropped, at most 100 chars>)` when the log has such a line.
  - When the GPU attempt fails and the CPU retry fails too, the attempts are joined as `GPU: it exited with code 1 (ggml_vulkan: No devices found); CPU: it did not answer within 60 s`. The person reads the detail `<that>. Showing keyword matches until it starts.`
  - `user_error.log` is `str(paths.logs_dir() / "llama-server.log")`, or `None` when the log could not be opened.
  - The log file `<data>/cache/logs/llama-server.log` holds the child's stdout and stderr together. It is truncated (`"wb"`) at every spawn, so after a GPU then CPU failure it holds the CPU attempt. The parent closes its handle as soon as the spawn returns, because the child keeps its own copy of the descriptor. `stop()` therefore has no handle to close, and a failed spawn closes it in a `finally`.
  - If the log cannot be opened (`OSError`), the server still starts with `stdout=DEVNULL`. A broken log directory must not turn off search by meaning.
  - Shared-server clients (`base_url=...`) spawn nothing and write no log. `connection_env` still passes `OMAFIND_EMBED_KEY` only through the indexer child's environment (main.py line 291, bin/omafind line 388).

**API key: what the tests can prove.**
- Proved: the key never appears in argv, which the existing `test_spawn_key_is_only_in_environment_and_authenticates` already covers. Our code writes nothing to the log; only the child's own output reaches it.
- Proved: the child did receive the key. The fake child prints its full argv and `LLAMA_API_KEY set: True`, never the value, and the test asserts that the fixed key string is absent from the log.
- Limitation: no unit test can prove that the real `llama-server` never prints its environment. It does not today. The spec's "fake server that prints its environment" would put the key in the log by construction, so it cannot be the test. The test pins what omafind controls.

- [ ] **Step 1: Write the failing tests**

In `tests/helper/test_embedder.py`, extend the imports (lines 1-25):

```python
import asyncio
import subprocess
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from fakes.embedder import FakeEmbedder
from fakes.llama_server import FakeSpawner, MemoryLlamaServer
from omafindd import embedder as embedder_module
from omafindd import errors, paths
from omafindd.embedder import (
```

(the `from omafindd.embedder import (...)` block is unchanged).

After the `inline_runner` fixture (after line 34), add:

```python
@pytest.fixture(autouse=True)
def data_home(tmp_path, monkeypatch):
    # The server log goes under the data directory.
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))


# Stands in for llama-server as a real child: prints its argv and whether it got the key,
# then exits with an error line or hangs, chosen per device by FAKE_LLAMA_GPU / FAKE_LLAMA_CPU.
FAKE_SERVER = """\
import os
import sys
import time

argv = sys.argv[1:]
print("argv:", *argv, flush=True)
print("LLAMA_API_KEY set:", "LLAMA_API_KEY" in os.environ, flush=True)
device = "CPU" if argv[argv.index("-ngl") + 1] == "0" else "GPU"
if os.environ.get("FAKE_LLAMA_" + device) == "exit":
    print("ggml_vulkan: No devices found.", file=sys.stderr, flush=True)
    print("main: cleaning up", file=sys.stderr, flush=True)
    sys.exit(1)
time.sleep(30)
"""
KEY = 'fixture-secret-key-0123456789'


@pytest.fixture
def fake_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(embedder_module.secrets, 'token_urlsafe', lambda size: KEY)
    path = tmp_path / 'fake-llama-server'
    path.write_text(f'#!{sys.executable} -S\n{FAKE_SERVER}')
    path.chmod(0o755)
    return path
```

The autouse fixture keeps every test in this file, including those that build the `runtime` fixture, from writing `llama-server.log` into the owner's real data directory. The binary is named `fake-llama-server`, so `pgrep -x llama-server` never matches it while the suite runs. The second line, `main: cleaning up`, proves that the cause is the last *matching* line, not simply the last line.

Replace `test_known_vram_start_failure_does_not_retry` (lines 393-399):

```python
async def test_known_vram_start_failure_does_not_retry(runtime):
    embedder, spawner = runtime
    spawner.server_options['health_status'] = 503
    with pytest.raises(EmbeddingError, match='start') as caught:
        await embedder.start('text')
    assert caught.value.user_error == errors.server_start_failed(
        'It did not answer within 0.2 s', paths.logs_dir() / 'llama-server.log')
    assert len(spawner.commands) == 1
    assert spawner.servers[0].terminated
```

Append at the end of the file (after line 630):

```python
async def test_start_sends_server_output_to_a_fresh_log(memory_runtime):
    embedder, spawner = memory_runtime
    log = paths.logs_dir() / 'llama-server.log'
    log.write_text('previous run\n')
    options = []

    async def spawn(*argv, **kwargs):
        options.append(kwargs)
        return await spawner(*argv, **kwargs)

    embedder.spawner = spawn
    try:
        await embedder.start('text')
        assert options[0]['stdout'].name == str(log)
        assert options[0]['stdout'].closed
        assert options[0]['stderr'] == asyncio.subprocess.STDOUT
        assert log.read_bytes() == b''
    finally:
        await embedder.stop()


async def test_start_runs_without_a_log_it_cannot_open(memory_runtime, monkeypatch, tmp_path):
    embedder, spawner = memory_runtime
    monkeypatch.setattr(paths, 'logs_dir', lambda: tmp_path / 'missing')
    options = []

    async def spawn(*argv, **kwargs):
        options.append(kwargs)
        return await spawner(*argv, **kwargs)

    embedder.spawner = spawn
    try:
        await embedder.start('text')
        assert options[0]['stdout'] == asyncio.subprocess.DEVNULL
    finally:
        await embedder.stop()


async def test_server_exit_keeps_its_cause_and_a_log_without_the_key(
        fake_binary, monkeypatch, tmp_path):
    monkeypatch.setenv('FAKE_LLAMA_GPU', 'exit')
    embedder = Embedder(binary=fake_binary, model_dir=tmp_path, startup_timeout=5,
                        runner=lambda *a, **kw: subprocess.CompletedProcess(a, 0, '4096'))
    with pytest.raises(EmbeddingError, match='^Embedding server failed to start$') as caught:
        await embedder.start('text')
    log = paths.logs_dir() / 'llama-server.log'
    assert caught.value.user_error == errors.server_start_failed(
        'It exited with code 1 (ggml_vulkan: No devices found)', log)
    text = log.read_text()
    assert '--port' in text and '-ngl 99' in text
    assert 'LLAMA_API_KEY set: True' in text
    assert KEY not in text


async def test_gpu_and_cpu_failures_are_both_named(fake_binary, monkeypatch, tmp_path):
    monkeypatch.setenv('FAKE_LLAMA_GPU', 'exit')

    def runner(*args, **kwargs):
        raise FileNotFoundError('nvidia-smi')

    embedder = Embedder(binary=fake_binary, model_dir=tmp_path, runner=runner,
                        startup_timeout=1, stop_timeout=1)
    with pytest.raises(EmbeddingError) as caught:
        await embedder.start('text')
    assert caught.value.user_error.detail.startswith(
        'GPU: it exited with code 1 (ggml_vulkan: No devices found); '
        'CPU: it did not answer within 1 s. ')
    text = (paths.logs_dir() / 'llama-server.log').read_text()
    assert '-ngl 0' in text
    assert '-ngl 99' not in text and 'No devices' not in text
    assert KEY not in text


async def test_missing_binary_names_the_os_error(tmp_path):
    embedder = Embedder(binary=tmp_path / 'absent', model_dir=tmp_path,
                        runner=lambda *a, **kw: subprocess.CompletedProcess(a, 0, '4096'))
    with pytest.raises(EmbeddingError) as caught:
        await embedder.start('text')
    assert caught.value.user_error.detail.startswith(
        'It could not be started (No such file or directory). ')
```

Notes on the tests:
- `test_gpu_and_cpu_failures_are_both_named` uses `startup_timeout=1` so the CPU child has time to print its argv under `nice -n 19` before it is terminated. It also proves the truncation, because the GPU attempt's lines are gone.
- The CPU child is `nice -n 19 <fake binary>`, as built by `server_argv`. `stop_timeout=1` bounds the SIGTERM wait. The parent-death signal also covers an aborted pytest run.

- [ ] **Step 2: Run them to see them fail**

```bash
uv run --project helper pytest -q tests/helper/test_embedder.py
```

Expected: 5 failed, the rest pass.
- `test_known_vram_start_failure_does_not_retry`, `test_server_exit_keeps_its_cause_and_a_log_without_the_key`, `test_gpu_and_cpu_failures_are_both_named` and `test_missing_binary_names_the_os_error` fail with `AssertionError: assert None == UserError(...)` or `AttributeError: 'NoneType' object has no attribute 'detail'`, because `user_error` is never set.
- `test_start_sends_server_output_to_a_fresh_log` fails with `AttributeError: 'int' object has no attribute 'name'`, because stdout is still `DEVNULL`.
- `test_start_runs_without_a_log_it_cannot_open` already passes. It guards the fallback added in Step 3.

- [ ] **Step 3: Add the imports**

In `helper/omafindd/embedder.py`, make lines 4-5 read:

```python
import os
import re
import secrets
```

and line 19 read:

```python
from omafindd import errors
from omafindd.models import FILES
```

- [ ] **Step 4: Add the log and cause helpers**

Replace the line `REQUEST_SLOTS = 2` (line 146) with:

```python
REQUEST_SLOTS = 2
SERVER_LOG = "llama-server.log"
_LOG_CAUSE = re.compile(r"error|failed|no devices", re.IGNORECASE)


def _open_log():
    from omafindd import paths

    try:
        path = paths.logs_dir() / SERVER_LOG
        return path, open(path, "wb")
    except OSError:
        return None, None


def _log_cause(path) -> str | None:
    """The last line of a server log that names an error, cut to 100 characters."""
    if path is None:
        return None
    try:
        tail = Path(path).read_bytes()[-65536:].decode(errors="replace")
    except OSError:
        return None
    line = next((line.strip() for line in reversed(tail.splitlines())
                 if _LOG_CAUSE.search(line)), None)
    if not line:
        return None
    line = line.rstrip(".")
    return line if len(line) <= 100 else line[:99].rstrip() + "…"


def _attempt_cause(error, log_path) -> str:
    clause = (str(error) if isinstance(error, EmbeddingError)
              else f"It could not be started ({error.strerror or error})")
    line = _log_cause(log_path)
    return clause if line is None else f"{clause} ({line})"


def _start_cause(causes) -> str:
    if len(causes) == 1:
        return causes[0][1]
    return "; ".join(f"{device.upper()}: {cause[:1].lower()}{cause[1:]}"
                     for device, cause in causes)
```

`_open_log` imports `paths` lazily, the same way `Embedder.start` already does. `_log_cause` reads at most the last 64 KiB, because a long-running server logs one line per request until its next start truncates the file.

- [ ] **Step 5: Send the server output to the log and keep the cause**

In `Embedder.start`, replace the device loop (lines 212-236: from `devices = [device, "cpu"] ...` through the `raise EmbeddingError("Embedding server failed to start") from error` line) with:

```python
            devices = [device, "cpu"] if free_mib is None else [device]
            causes = []
            for attempt, device in enumerate(devices):
                log_path = None
                try:
                    with socket.socket() as sock:
                        sock.bind(("127.0.0.1", 0))
                        port = sock.getsockname()[1]
                    api_key = secrets.token_urlsafe(32)
                    self._api_key = api_key
                    # Truncated per attempt, so after a GPU then CPU failure it holds the CPU run.
                    log_path, log = _open_log()
                    try:
                        # The key goes only in the environment, never in argv.
                        self._process = await self.spawner(
                            *build_command(binary, directory, mode, device, port),
                            env={**os.environ, "LLAMA_API_KEY": api_key},
                            stdout=asyncio.subprocess.DEVNULL if log is None else log,
                            stderr=asyncio.subprocess.STDOUT,
                            preexec_fn=partial(_parent_death_signal, os.getpid())
                            if sys.platform == "linux" else None,
                        )
                    finally:
                        if log is not None:
                            log.close()
                    self._client = httpx.AsyncClient(
                        base_url=f"http://127.0.0.1:{port}",
                        headers={"Authorization": f"Bearer {api_key}"},
                        trust_env=False, timeout=30,
                    )
                    await self._wait_ready(self._process, self._client)
                except (OSError, EmbeddingError) as error:
                    await self._stop()
                    causes.append((device, _attempt_cause(error, log_path)))
                    if attempt == len(devices) - 1:
                        raise EmbeddingError(
                            "Embedding server failed to start",
                            user_error=errors.server_start_failed(_start_cause(causes), log_path),
                        ) from error
```

The `except BaseException`, `else` branches that follow stay as they are. The log line is read after `self._stop()`, so a terminated child has flushed its last output before we read it.

- [ ] **Step 6: Make `_wait_ready` raise cause clauses**

Replace the tail of `_wait_ready` (lines 255-257):

```python
        except TimeoutError as error:
            raise EmbeddingError("Embedding server start timed out") from error
        raise EmbeddingError("Embedding server exited during start")
```

with:

```python
        except TimeoutError as error:
            raise EmbeddingError(f"It did not answer within {self.startup_timeout:g} s") from error
        code = process.returncode
        raise EmbeddingError(f"It was stopped by signal {-code}" if code < 0
                             else f"It exited with code {code}")
```

No other module matches the old strings: `grep -rn "timed out\|exited during start"` finds only these two lines.

- [ ] **Step 7: Run the embedder tests**

```bash
uv run --project helper pytest -q tests/helper/test_embedder.py tests/helper/test_index_lease.py
pgrep -x llama-server || echo none
```

Expected: all pass, then `none`.

- [ ] **Step 8: Run the full checks**

```bash
uv run --project helper pytest -q
node --test "tests/js/*.test.mjs"
uv run --project helper ruff check helper tests bin/omafind scripts evals
scripts/qmllint.sh
git diff --check
```

All five must pass (integration run: `1011 passed`, JS `226` pass). `pgrep -x llama-server` must still print nothing.

- [ ] **Step 9: Commit**

```bash
git add helper/omafindd/embedder.py tests/helper/test_embedder.py
git status --short
git diff --staged --stat
git commit -S -m "fix(omafindd): keep the embedding server log and the start cause"
```

---

### Task 5: Name per-file failures and missing tools

**Files:**

- Create: `helper/omafindd/failures.py` (per-file codes and how `files.detail` stores them).
- Modify:
  - `helper/omafindd/extractors.py`: `ExtractionError` at 22-23; `extract_text` 121; `_pdf_command` 146-156; `extract_pdf` 163 and 175; `_media_command` 244-251; `_stream` 282-294; `keyframes` 394; `extract_audio` 422 and 436.
  - `helper/omafindd/jobs.py`: imports 14; extraction mapping 165-180; soundtrack halt 268-273; failure handlers 295-314.
  - `helper/omafindd/store.py`: imports 9; `fail` and `halt` 287-297.
  - `helper/omafindd/code.py`: imports 10; code-index failure 294-297.
  - `helper/omafindd/tools.py`: add `TOOL_FEATURES` after `TOOLS` (5-17).
  - `helper/omafindd/setup.py`: imports 13; `TYPES` 26-38; `handle` (new branch before the final unknown-request return, 187 before Task 2); new `_retry_failed` and a rewritten `_progress` at 413-501.
- Test: `tests/helper/test_failures.py` (new), `test_jobs.py`, `test_ipc_setup.py`, `test_code.py`, `test_extract_pdf.py`, `test_ocr.py`, `test_audio.py`, `test_video.py`, `test_store.py`, `test_tools.py`.

The line ranges are from `4925220`. Tasks 2 and 3 move lines in `setup.py` and `tools.py`, so anchor each hunk on its text, not its number.

**Storage decision.** The index has no migrations. `Store.__init__` and `CodeStore.__init__` accept only `user_version == 5` and raise `Unsupported index schema` for anything else. Bumping the version would make every existing index unusable, and a rebuild re-embeds every file. Adding a column would break `SetupService._progress`, `ipc.py` status and `bin/omafind status`. They read every `*.sqlite` directly and would fail on a store that the new indexer has not opened yet. `files.detail` already has three meanings: failure reason (`failed`), skip reason (`skipped`) and halt marker (`partial` with a non-null detail leaves the queue). So the code goes into the existing column as `code` or `code: detail`. `failures.decode` splits on the first `": "`, which no code contains, and maps the four sentences older daemons wrote (`embedding precision fault` and others) to their codes. Any other old text becomes the store's fallback code (`extract-failed`, or `code-index-failed` for `code.sqlite`) and keeps the text as its detail. Rows from older daemons need no rewrite, and the `detail IS NULL` resume rule is unchanged.

**Retry decision.** `Jobs.drain` takes only `state='pending' OR (state='partial' AND detail IS NULL)`, and `reconcile` re-queues a file only when its size, mtime or kind changes. So a failed file stays failed until the person edits it. `retry_failed` applies the reset that `reconcile` uses for changed files (`state='pending',detail=NULL,info=NULL,indexed_at=NULL`) to each failed row whose decoded code matches. It then calls `SetupService.kick()`, the path that `Freshness.tick` uses to start indexing:
- No run is active: `kick` spawns `reindex --incremental`. Its crawl leaves unchanged pending rows pending, and `drain` picks them up.
- A run is active: `kick` adds `None` to `_deferred`, and `poll` starts one more pass when the run exits. A running `drain` that has not finished that store also picks up the rows, because it selects the next 64 pending rows on each loop.
- The disk guard is paused or the model is not ready: `kick` returns, and the rows stay pending for the next pass.

`code.sqlite` is left out of the retry: `index_code` re-embeds every row that is not `done` on every pass.

**Interfaces:**

- Consumes:
  - `errors.tool_missing(count, tool, what, package)`, `errors.bad_request(reason)`, `errors.reply(kind, error)` (Task 1);
  - `tools.TOOLS` (tool to package; Task 3 keeps it);
  - the Task 2 shape of `SetupService.handle`, where an unexpected exception becomes `errors.internal`;
  - `SetupService.kick()` and `_deferred` (existing).
- Produces:
  - `failures.CODES`: `encrypted-pdf`, `timeout`, `extract-failed`, `embedding-failed`, `embedding-precision-fault`, `soundtrack-failed`, `audio-off`, `silent-audio`, `tool-missing`, `code-index-failed`.
  - `failures.encode(code, detail="") -> str` and `failures.decode(value, fallback="extract-failed") -> (code, detail)`.
  - `ExtractionError(code, detail="")` with `.code` and `.detail`. `str()` is the encoded value, so a single-argument `ExtractionError("rg failed")` in `preview.py` still prints `rg failed`.
  - `Store.fail(file, code, detail="")` and `Store.halt(file, code, detail="")`.
  - `tools.TOOL_FEATURES` (tool to the `what` clause).
  - `progress.problems: [{path, code, detail}]` (at most 50, `code.sqlite` rows included, with paths relative to `/`).
  - `progress.failed: {code: count}`, including `code-index-failed`.
  - `progress.tool_errors: [UserError dict]`, one `tool-missing` object per missing tool, sorted by tool name. It is `[]` when no file waits on a tool.
  - Request `{"t":"retry_failed","code":"<code>"}`, with reply `{"t":"retry_failed","code":"<code>","count":n}` or `errors.reply("retry_failed", errors.bad_request("Unknown failure code"))`.
- For Task 8 to document: the `progress.problems` and `progress.tool_errors` shapes, `retry_failed`, the stored skip details `audio-off` and `silent-audio` (docs/ipc.md lines 127-129 and README line 176 still say `audio search is off` and `silent audio`), and `embedding-failed: <cause>` (docs/ipc.md line 287).

- [ ] **Step 1: Write the failing tests**

Create `tests/helper/test_failures.py`:

```python
import pytest
from omafindd import failures


def test_encode_keeps_the_code_and_one_short_line():
    assert failures.encode("timeout") == "timeout"
    assert failures.encode("tool-missing", "tesseract") == "tool-missing: tesseract"
    assert failures.encode("extract-failed", "\n  first\nsecond") == "extract-failed: first"
    assert failures.encode("extract-failed", "x" * 300) == "extract-failed: " + "x" * 200


@pytest.mark.parametrize("value,fallback,expected", [
    (None, "extract-failed", ("extract-failed", "")),
    ("encrypted-pdf", "extract-failed", ("encrypted-pdf", "")),
    ("tool-missing: tesseract", "extract-failed", ("tool-missing", "tesseract")),
    ("embedding-failed: HTTP 500: too large", "extract-failed",
     ("embedding-failed", "HTTP 500: too large")),
    ("embedding precision fault", "extract-failed", ("embedding-precision-fault", "")),
    ("soundtrack embedding failed", "extract-failed", ("soundtrack-failed", "")),
    ("audio search is off", "extract-failed", ("audio-off", "")),
    ("silent audio", "extract-failed", ("silent-audio", "")),
    ("HTTP 500: too large", "code-index-failed", ("code-index-failed", "HTTP 500: too large")),
])
def test_decode_reads_codes_and_older_sentences(value, fallback, expected):
    assert failures.decode(value, fallback) == expected


def test_every_code_round_trips():
    for code in failures.CODES:
        assert failures.decode(failures.encode(code, "why")) == (code, "why")
```

In `tests/helper/test_jobs.py`:

- In `test_nan_vector_fails_file` and `test_runtime_precision_fault_fails_file`, replace both expected tuples `("failed", "embedding precision fault")` with `("failed", "embedding-precision-fault")`. The text appears twice; replace both.
- Replace the `test_poison_file_does_not_abort_or_remain_pending` parameter list with:

```python
@pytest.mark.parametrize(
    "error,detail",
    [
        (zlib.error("fixture"), "extract-failed: fixture"),
        (NotImplementedError("fixture"), "extract-failed: fixture"),
        (RuntimeError(), "extract-failed: RuntimeError"),
        (ValueError("bad image dimensions"), "extract-failed: bad image dimensions"),
        (subprocess.TimeoutExpired("pdfinfo", 60),
         "timeout: Command 'pdfinfo' timed out after 60 seconds"),
        (ExtractionError("timeout", "pdfinfo"), "timeout: pdfinfo"),
        (ExtractionError("encrypted-pdf"), "encrypted-pdf"),
        (ExtractionError("pdftoppm failed"), "extract-failed: pdftoppm failed"),
        (ExtractionError("extract-failed", "pdfinfo failed: Syntax Error: bad xref"),
         "extract-failed: pdfinfo failed: Syntax Error: bad xref"),
        (ExtractionError("tool-missing", "pdftoppm"), "tool-missing: pdftoppm"),
    ],
)
```

- In `test_broken_pool_is_rebuilt_for_remaining_files`, replace `assert detail == "extract-failed"` with `assert detail == "extract-failed: the extraction worker stopped"`.
- In `test_rejected_file_fails_and_the_run_continues`, replace the `states` assertion with:

```python
    assert states == {
        "bad.txt": "failed:embedding-failed: HTTP 500: input (3359 tokens) is too large",
        "good.txt": "done:",
    }
```

- In `test_rejected_pdf_window_keeps_earlier_pages`, replace the row assertion with `assert tuple(row) == ("partial", "embedding-failed: HTTP 500: too large")`.
- In `test_text_batch_precision_fault_fails_only_the_bad_file`, replace `("bad.txt", "failed", "embedding precision fault")` with `("bad.txt", "failed", "embedding-precision-fault")`.
- In the last rejected-batch test (the assertion that starts `)] == [("bad.txt", "failed", "embedding-failed"), ("one.txt", "done", None),`), replace that line with:

```python
    )] == [("bad.txt", "failed", "embedding-failed: HTTP 500: fixture rejected"),
          ("one.txt", "done", None),
```

In `tests/helper/test_code.py`, in the `Invalid` embedder block, replace `"failed", "embedding precision fault"` with `"failed", "code-index-failed: embedding precision fault"`.

In `tests/helper/test_audio.py`, replace `("skipped", "audio search is off" if off else "silent audio")` with `("skipped", "audio-off" if off else "silent-audio")`.

In `tests/helper/test_video.py`, in `test_media_precision_failure_preserves_only_valid_frames`, replace `"failed" if frames_fail else "partial", "embedding precision fault",` with `"failed" if frames_fail else "partial", "embedding-precision-fault",`. Then append:

```python


def test_media_commands_name_a_missing_tool_and_keep_the_error_line():
    from omafindd.extractors import ExtractionError, _media_command, _stream

    script = "echo 'Warning: ignored' >&2; echo 'Error: bad header' >&2; exit 3"
    for call in (lambda argv: _media_command(argv), lambda argv: list(_stream(argv, 64))):
        with pytest.raises(ExtractionError) as missing:
            call(["omafind-no-such-tool"])
        assert (missing.value.code, missing.value.detail) == (
            "tool-missing", "omafind-no-such-tool")
        with pytest.raises(ExtractionError) as failed:
            call(["sh", "-c", script])
        assert (failed.value.code, failed.value.detail) == (
            "extract-failed", "sh failed: Error: bad header")
```

In `tests/helper/test_extract_pdf.py`, change the end of `test_pdf_tools_have_timeout_and_report_timeout` to:

```python
    with pytest.raises(ExtractionError, match=f"^timeout: {tool}$") as caught:
        _pdf_command([tool, "fixture"])
    assert (caught.value.code, caught.value.detail) == ("timeout", tool)
```

and append:

```python


def test_missing_pdf_tool_is_named(tmp_path, monkeypatch):
    from omafindd.extractors import ExtractionError, extract_pdf

    root = copy_corpus(tmp_path / "corpus")
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(ExtractionError) as caught:
        extract_pdf(root / "invoice.pdf")
    assert (caught.value.code, caught.value.detail) == ("tool-missing", "pdfinfo")


def test_failed_pdf_tool_keeps_its_error_line(tmp_path):
    from omafindd.extractors import ExtractionError, extract_pdf

    path = tmp_path / "broken.pdf"
    path.write_text("not a pdf")
    with pytest.raises(ExtractionError) as caught:
        extract_pdf(path)
    assert caught.value.code == "extract-failed"
    assert caught.value.detail.startswith("pdfinfo failed: Syntax Error")
```

Append to `tests/helper/test_ocr.py`. `crawl` runs `fd`, so `PATH` is narrowed only after the crawl:

```python


async def test_missing_tesseract_fails_the_screenshot_as_tool_missing(tmp_path, monkeypatch):
    import shutil

    from omafindd import jobs
    from omafindd.crawler import crawl
    from omafindd.store import Store

    files = tmp_path / "files"
    files.mkdir()
    command("magick", "-size", "1200x160", "xc:white", str(files / "screenshot-text.png"))
    tools = tmp_path / "bin"
    tools.mkdir()
    (tools / "magick").symlink_to(shutil.which("magick"))
    monkeypatch.setattr(jobs, "ProcessPoolExecutor", InlinePool)
    store = Store(tmp_path / "index/v.sqlite", volume="v", mount=files)
    try:
        crawl(store, [{"path": str(files)}])
        monkeypatch.setenv("PATH", str(tools))
        await jobs.Jobs(store, FakeEmbedder(), journal=tmp_path / "journal").drain()
        assert tuple(store.db.execute("SELECT state,detail FROM files").fetchone()) == (
            "failed", "tool-missing: tesseract")
    finally:
        store.close()
```

Append to `tests/helper/test_tools.py`:

```python


def test_every_extraction_tool_says_what_it_gives_and_has_a_package():
    from omafindd.tools import TOOL_FEATURES, TOOLS

    assert set(TOOL_FEATURES) == {
        "magick", "pdfinfo", "pdftotext", "pdftoppm", "ffprobe", "ffmpeg", "tesseract"
    }
    assert set(TOOL_FEATURES) <= set(TOOLS)
```

Append to `tests/helper/test_store.py`:

```python


def test_fail_and_halt_store_the_code_with_its_detail(store, tmp_path):
    from omafindd.crawler import crawl

    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text("fixture")
    first, second = crawl(store, [{"path": str(tmp_path)}])
    store.fail(first, "tool-missing", "tesseract")
    with store.db:
        store.db.execute("UPDATE files SET state='partial' WHERE id=?", (second,))
    store.halt(second, "embedding-failed", "HTTP 500: too large\nmore")
    assert [tuple(row) for row in store.db.execute(
        "SELECT state,detail FROM files ORDER BY path"
    )] == [("failed", "tool-missing: tesseract"),
           ("partial", "embedding-failed: HTTP 500: too large")]
```

In `tests/helper/test_ipc_setup.py`, add `import sqlite3` after `import os`. In `test_progress_body_from_stores`, replace the `problems` assertion with:

```python
    assert result["problems"] == [{"path": "/h/e.pdf", "code": "encrypted-pdf", "detail": ""}]
    assert result["tool_errors"] == []
```

Then insert the following right before the `@pytest.mark.parametrize("message", ...)` that decorates `test_bad_request`:

```python
def _failed_rows(service, rows):
    store = Store(service.data_dir / "index/u.sqlite", volume="u", mount=Path("/h"))
    for index, (path, state, detail) in enumerate(rows, 1):
        store.db.execute(
            "INSERT INTO files(id,path,kind,size,mtime,inode,device,state,detail) "
            "VALUES(?,?,'text',0,0,0,0,?,?)",
            (index, path, state, detail),
        )
    store.db.commit()
    store.close()


async def test_progress_names_failures_missing_tools_and_code_index(service):
    from omafindd import errors
    from omafindd.code import CodeStore

    _failed_rows(service, [
        ("a.png", "failed", "tool-missing: tesseract"),
        ("b.png", "failed", "tool-missing: tesseract"),
        ("c.pdf", "failed", "extract-failed: pdfinfo failed: Syntax Error"),
        ("d.txt", "failed", "embedding precision fault"),
        ("e.mp4", "failed", "tool-missing: ffprobe"),
    ])
    code = CodeStore(service.data_dir / "index/code.sqlite")
    code.db.execute(
        "INSERT INTO files(path,kind,size,mtime,inode,device,state,detail) "
        "VALUES('src/repo/bad.py','code',0,0,0,0,'failed','HTTP 500: too large')"
    )
    code.db.commit()
    code.close()
    result = await service.handle({"t": "index_progress"})
    assert result["failed"] == {"tool-missing": 3, "extract-failed": 1,
                                "embedding-precision-fault": 1, "code-index-failed": 1}
    assert result["problems"] == [
        {"path": "/src/repo/bad.py", "code": "code-index-failed", "detail": "HTTP 500: too large"},
        {"path": "/h/a.png", "code": "tool-missing", "detail": "tesseract"},
        {"path": "/h/b.png", "code": "tool-missing", "detail": "tesseract"},
        {"path": "/h/c.pdf", "code": "extract-failed",
         "detail": "pdfinfo failed: Syntax Error"},
        {"path": "/h/d.txt", "code": "embedding-precision-fault", "detail": ""},
        {"path": "/h/e.mp4", "code": "tool-missing", "detail": "ffprobe"},
    ]
    assert result["tool_errors"] == [
        errors.tool_missing(1, "ffprobe", "video and audio", "ffmpeg").to_dict(),
        errors.tool_missing(2, "tesseract", "text recognition", "tesseract").to_dict(),
    ]
    assert list(result["volumes"]) == ["u"]
    assert result["kinds"]["text"] == {"done": 5, "total": 5}


async def test_retry_failed_queues_only_that_code_and_starts_indexing(service):
    _failed_rows(service, [
        ("a.png", "failed", "tool-missing: tesseract"),
        ("b.pdf", "failed", "encrypted-pdf"),
        ("c.mp4", "failed", "tool-missing: ffprobe"),
        ("d.txt", "done", None),
    ])
    assert await service.handle({"t": "retry_failed", "code": "tool-missing"}) == {
        "t": "retry_failed", "code": "tool-missing", "count": 2,
    }
    db = sqlite3.connect(service.data_dir / "index/u.sqlite")
    try:
        assert db.execute("SELECT path,state,detail FROM files ORDER BY path").fetchall() == [
            ("a.png", "pending", None), ("b.pdf", "failed", "encrypted-pdf"),
            ("c.mp4", "pending", None), ("d.txt", "done", None),
        ]
    finally:
        db.close()
    assert len(service.test_calls) == 1


async def test_retry_failed_during_a_run_indexes_after_it(service):
    _failed_rows(service, [("a.png", "failed", "tool-missing: tesseract")])
    await service.handle({"t": "index_start"})
    reply = await service.handle({"t": "retry_failed", "code": "tool-missing"})
    assert reply["count"] == 1 and len(service.test_calls) == 1
    service.test_process.returncode = 0
    await service.poll(now=0)
    assert len(service.test_calls) == 2


async def test_retry_failed_without_matches_starts_nothing(service):
    _failed_rows(service, [("b.pdf", "failed", "encrypted-pdf")])
    assert await service.handle({"t": "retry_failed", "code": "tool-missing"}) == {
        "t": "retry_failed", "code": "tool-missing", "count": 0,
    }
    assert not service.test_calls


@pytest.mark.parametrize("code", [None, "", "missing", ["tool-missing"]])
async def test_retry_failed_rejects_unknown_codes(service, code):
    from omafindd import errors

    assert await service.handle({"t": "retry_failed", "code": code}) == errors.reply(
        "retry_failed", errors.bad_request("Unknown failure code")
    )
    assert not service.test_calls
```

`test_setup_messages_are_ignored_before_hello` is parametrized over `SetupService.TYPES`, so it covers `retry_failed` once Step 8 adds the type.

- [ ] **Step 2: Run them to see them fail**

```bash
uv run --project helper pytest -q tests/helper/test_failures.py tests/helper/test_jobs.py \
  tests/helper/test_ipc_setup.py tests/helper/test_code.py tests/helper/test_extract_pdf.py \
  tests/helper/test_ocr.py tests/helper/test_audio.py tests/helper/test_video.py \
  tests/helper/test_store.py tests/helper/test_tools.py
```

Expected failures:
- `test_failures.py` fails on `ModuleNotFoundError: No module named 'omafindd.failures'`.
- `test_tools.py` fails on `ImportError: cannot import name 'TOOL_FEATURES'`.
- `test_jobs.py`, `test_code.py`, `test_audio.py` and `test_video.py` fail on assertion mismatches: the stored values are still the old sentences.
- In `test_extract_pdf.py`, the timeout test fails on `^timeout: pdfinfo$`, and the missing-tool test fails because `FileNotFoundError` escapes.
- In `test_ocr.py`, the tesseract test reads `('failed', 'extract-failed')`.
- In `test_store.py`, the new test fails because `fail()` takes two positional arguments.
- In `test_ipc_setup.py`, the progress tests fail on the `reason` key and the missing `tool_errors`. The `retry_failed` tests receive the unknown-request `bad-request` reply, and the parametrized bad-code test passes only by accident.

- [ ] **Step 3: Add the failure codes module**

Create `helper/omafindd/failures.py`:

```python
"""Per-file failure codes. `files.detail` stores one as `code` or `code: detail`."""

CODES = (
    "encrypted-pdf",
    "timeout",
    "extract-failed",
    "embedding-failed",
    "embedding-precision-fault",
    "soundtrack-failed",
    "audio-off",
    "silent-audio",
    "tool-missing",
    "code-index-failed",
)
# Indexes written before the codes existed stored these sentences.
LEGACY = {
    "embedding precision fault": "embedding-precision-fault",
    "soundtrack embedding failed": "soundtrack-failed",
    "audio search is off": "audio-off",
    "silent audio": "silent-audio",
}


def encode(code: str, detail="") -> str:
    """The stored value. `detail` keeps its first non-empty line, cut to 200 characters."""
    line = next((part.strip() for part in str(detail).splitlines() if part.strip()), "")
    return f"{code}: {line[:200]}" if line else code


def decode(value: str | None, fallback: str = "extract-failed") -> tuple[str, str]:
    """`(code, detail)` from a stored value. Any other text becomes `fallback` with it as detail."""
    if not value:
        return fallback, ""
    if value in LEGACY:
        return LEGACY[value], ""
    code, _, detail = value.partition(": ")
    return (code, detail) if code in CODES else (fallback, value)
```

`CODES` is a tuple, so `["tool-missing"] in failures.CODES` returns False instead of raising `TypeError: unhashable type`.

- [ ] **Step 4: Give extractor failures a code and keep the tool's message**

In `helper/omafindd/extractors.py`, replace the import line and the class:

```python
from . import failures
from .rules import screenshot_like


class ExtractionError(Exception):
    """A file that cannot be indexed: `code` is in failures.CODES, `detail` the tool's message."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code, detail)
        self.code, self.detail = code, detail

    def __str__(self):
        return failures.encode(self.code, self.detail)
```

`ProcessPoolExecutor` pickles the exception as `cls(*args)`, so `code` and `detail` survive the worker boundary.

In `extract_text`, use `raise ExtractionError("extract-failed", "unreadable Office file") from error`.

Replace `_pdf_command` with these three functions:

```python
def _run(argv, **kwargs) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, timeout=60, **kwargs)
    except subprocess.TimeoutExpired as error:
        raise ExtractionError("timeout", argv[0]) from error
    except FileNotFoundError as error:
        raise ExtractionError("tool-missing", argv[0]) from error


def _failed(argv, stderr) -> ExtractionError:
    """`extract-failed` with the tool's first error line, else its last line."""
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    line = next((line for line in lines if "error" in line.lower()), lines[-1] if lines else "")
    return ExtractionError("extract-failed", f"{argv[0]} failed: {line}" if line
                           else f"{argv[0]} failed")


def _pdf_command(argv, *, text=True):
    result = _run(argv, text=text)
    if result.returncode:
        detail = result.stderr if text else result.stderr.decode(errors="replace")
        if "Incorrect password" in detail:
            raise ExtractionError("encrypted-pdf")
        raise _failed(argv, detail)
    return result.stdout
```

poppler prints `Syntax Warning: May not be a PDF file` before the real error, so `_failed` prefers a line that mentions an error.

In `extract_pdf`, change the two remaining raises to `ExtractionError("extract-failed", "pdfinfo returned no page count")` and `ExtractionError("extract-failed", "pdftotext returned an unexpected page count")`.

Replace `_media_command`:

```python
def _media_command(argv, *, data=None) -> bytes:
    result = _run(argv, input=data)
    if result.returncode:
        raise _failed(argv, result.stderr)
    return result.stdout
```

Replace the body of `_stream`, keeping its comment:

```python
def _stream(argv, size: int) -> Iterator[bytes]:
    # A file for stderr prevents pipe deadlock while stdout is consumed incrementally.
    with tempfile.TemporaryFile() as errors:
        try:
            process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=errors)
        except FileNotFoundError as error:
            raise ExtractionError("tool-missing", argv[0]) from error
        with process:
            try:
                while block := process.stdout.read(size):
                    yield block
                if process.wait():
                    errors.seek(0)
                    raise _failed(argv, errors.read())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
```

Make three more changes in the same file:
- In `keyframes`, use `raise ExtractionError("extract-failed", "incomplete frame sample")`.
- In `extract_audio`, use `detail="audio-off"` and `detail="silent-audio" if state == "skipped" else None`.
- Leave `result.state, result.detail = "partial", str(error)` in `extract_video` as it is. `str(error)` is now the encoded `code: detail`.

- [ ] **Step 5: Store the code and detail**

In `helper/omafindd/store.py`, add `from . import failures` above `from .models import REVISION`, and replace `fail` and `halt`:

```python
    def fail(self, file: int, code: str, detail: str = ""):
        self._thumbnail_path(file).unlink(missing_ok=True)
        with self.db:
            self.clear_segments(file, keeping_name=True)
            self.db.execute("UPDATE files SET state='failed',detail=? WHERE id=?",
                            (failures.encode(code, detail), file))

    def halt(self, file: int, code: str, detail: str = ""):
        """Stops a partial file where it is: its segments stay and it leaves the queue."""
        with self.db:
            self.db.execute("UPDATE files SET detail=? WHERE id=? AND state='partial'",
                            (failures.encode(code, detail), file))
```

In `helper/omafindd/code.py`, add `from . import failures` above `from .rules import reason`, and replace the failure write in `index_code`:

```python
                except (EmbeddingError, OSError, ValueError) as error:
                    with store.db:
                        store.db.execute(
                            "UPDATE files SET state='failed',detail=? WHERE id=?",
                            (failures.encode("code-index-failed", str(error)), file),
                        )
```

- [ ] **Step 6: Map every indexing failure to a code**

In `helper/omafindd/jobs.py`, add `from . import failures` above `from .embedder import (`.

Replace the extraction handlers inside `drain` (from the `raise ExtractionError("extract-failed") from error` after the pool rebuild through `raise ExtractionError(detail) from error`):

```python
                            raise ExtractionError(
                                "extract-failed", "the extraction worker stopped"
                            ) from error
                        except ExtractionError as error:
                            if error.code in failures.CODES:
                                raise
                            raise ExtractionError("extract-failed", str(error)) from error
                        except subprocess.TimeoutExpired as error:
                            raise ExtractionError("timeout", str(error)) from error
                        except Exception as error:
                            raise ExtractionError(
                                "extract-failed", str(error) or type(error).__name__
                            ) from error
```

Replace the soundtrack halt detail:

```python
                                result.detail = (
                                    failures.encode("embedding-precision-fault")
                                    if isinstance(error, ValueError)
                                    or str(error) == "embedding precision fault"
                                    else failures.encode("soundtrack-failed", str(error))
                                )
```

Replace the handlers from `except ExtractionError as error:` through the end of the old `except Exception` block. Leave the `finally:` as it is:

```python
                    except ExtractionError as error:
                        self.store.fail(file, error.code, error.detail)
                    except EmbeddingRejected as error:
                        logger.warning("Embedding rejected file %s (%s)", file, error)
                        if append:
                            self.store.halt(file, "embedding-failed", str(error))
                        else:
                            self.store.fail(file, "embedding-failed", str(error))
                    except EmbeddingError as error:
                        if str(error) != "embedding precision fault":
                            raise
                        self.store.fail(file, "embedding-precision-fault")
                    except ValueError as error:
                        if str(error) == "embedding precision fault":
                            self.store.fail(file, "embedding-precision-fault")
                        else:
                            self.store.fail(file, "extract-failed", str(error))
                    except Exception as error:
                        self.store.fail(file, "extract-failed", str(error) or type(error).__name__)
```

The embedder bounds `EmbeddingRejected` messages to `HTTP <status>: <server message>` (200 characters) and never includes document text, so they are safe to store.

- [ ] **Step 7: Say what each extraction tool gives**

In `helper/omafindd/tools.py`, add the following directly after the closing `}` of `TOOLS`. Task 3's `BUILD_NEEDS` goes elsewhere in the file:

```python
# What a file is indexed without when the tool is missing (errors.tool_missing `what`).
TOOL_FEATURES = {
    "magick": "image support",
    "pdfinfo": "PDF text",
    "pdftotext": "PDF text",
    "pdftoppm": "PDF page images",
    "ffprobe": "video and audio",
    "ffmpeg": "video and audio",
    "tesseract": "text recognition",
}
```

- [ ] **Step 8: Report failures in progress and add `retry_failed`**

In `helper/omafindd/setup.py`:

1. Import: `from . import bindings, discovery, errors, failures, tools`. Task 2 already imports `errors`, so add only `failures` and `tools`.
2. Add `"retry_failed",` to `SetupService.TYPES` after `"drive_decision",`.
3. In `handle`, add this branch directly after the `index_start` branch, before the final unknown-request return:

```python
            if kind == "retry_failed":
                code = message.get("code")
                if code not in failures.CODES:
                    return errors.reply(kind, errors.bad_request("Unknown failure code"))
                count = await asyncio.to_thread(self._retry_failed, code)
                if count:
                    await self.kick()
                return {"t": kind, "code": code, "count": count}
```

A locked or unreadable store raises out of `_retry_failed`. The `except Exception` from Task 2 turns that into an `internal` error with a Retry fix, so a retry is never lost without a message.

4. Replace `def _progress(self):` through its `return {...}` with the following, which also adds `_retry_failed` above it:

```python
    def _retry_failed(self, code):
        """Queues the failed files whose failure is `code` again and returns how many.

        The code index is left alone: every pass retries its failed files.
        """
        count = 0
        for path in sorted((self.data_dir / "index").glob("*.sqlite")):
            if path.name == "code.sqlite":
                continue
            with closing(
                sqlite3.connect(path.absolute().as_uri() + "?mode=rw", uri=True, timeout=5)
            ) as db, db:
                ids = [(file,) for file, detail in db.execute(
                    "SELECT id,detail FROM files WHERE state='failed'"
                ) if failures.decode(detail)[0] == code]
                db.executemany(
                    "UPDATE files SET state='pending',detail=NULL,info=NULL,indexed_at=NULL "
                    "WHERE id=? AND state='failed'", ids,
                )
                count += len(ids)
        return count

    def _progress(self):
        kinds = {kind: {"done": 0, "total": 0} for kind in KINDS}
        kinds["pdf"]["pages"] = kinds["image"]["ocr"] = 0
        failed, problems, volumes, missing = {}, [], {}, {}
        volume = pending_volume = None
        try:
            self._mounts = mounted_volumes()
        except (OSError, subprocess.SubprocessError):
            pass
        ready = "NOT (state='pending' OR (state='partial' AND detail IS NULL))"
        for path in sorted((self.data_dir / "index").glob("*.sqlite")):
            code_index = path.name == "code.sqlite"
            try:
                with closing(
                    sqlite3.connect(path.absolute().as_uri() + "?mode=rw", uri=True, timeout=0.05)
                ) as db:
                    meta = dict(db.execute("SELECT key,value FROM meta"))
                    current = meta.get("volume_uuid", path.stem)
                    if not code_index:
                        volume = current
                        total, done = db.execute(
                            f"SELECT count(*),coalesce(sum({ready}),0) FROM files"
                        ).fetchone()
                        volumes[current] = {"label": meta.get("volume_label", "root"),
                                            "done": done, "total": total}
                        for kind, total, done in db.execute(
                            f"SELECT kind,count(*),sum({ready}) FROM files GROUP BY kind"
                        ):
                            if kind not in kinds:
                                continue
                            kinds[kind]["total"] += total
                            kinds[kind]["done"] += done or 0
                            if total != done:
                                pending_volume = current
                        kinds["pdf"]["pages"] += db.execute(
                            "SELECT coalesce(sum(json_extract(info,'$.pages')),0) FROM files "
                            f"WHERE kind='pdf' AND {ready}"
                        ).fetchone()[0]
                        kinds["image"]["ocr"] += db.execute(
                            "SELECT count(*) FROM files f WHERE kind='image' AND "
                            + ready
                            + " AND EXISTS (SELECT 1 FROM segments s JOIN fts ON fts.rowid=s.id "
                            "WHERE s.file=f.id AND s.kind='ocr' AND length(fts.body)>0)"
                        ).fetchone()[0]
                    fallback = "code-index-failed" if code_index else "extract-failed"
                    for value, count in db.execute(
                        "SELECT detail,count(*) FROM files WHERE state='failed' GROUP BY detail"
                    ):
                        code, detail = failures.decode(value, fallback)
                        failed[code] = failed.get(code, 0) + count
                        if code == "tool-missing" and detail in tools.TOOL_FEATURES:
                            missing[detail] = missing.get(detail, 0) + count
                    # Code index paths are relative to /.
                    mount = Path("/") if code_index else self._mounts.get(current)
                    if mount is not None:
                        for rel, value in db.execute(
                            "SELECT path,detail FROM files WHERE state='failed' "
                            "ORDER BY path LIMIT ?",
                            (50 - len(problems),),
                        ):
                            code, detail = failures.decode(value, fallback)
                            problems.append(
                                {"path": str(mount / rel), "code": code, "detail": detail}
                            )
            except sqlite3.Error:
                continue
        skipped = {}
        try:
            run = json.loads((self.data_dir / "index/run.json").read_text())
            if self._index is None or run.get("pid") == self._index.pid:
                skipped = {
                    k: n for k, n in run.get("skipped", {}).items() if type(n) is int and n > 0
                }
        except (OSError, ValueError, AttributeError):
            pass
        done = sum(kind["done"] for kind in kinds.values())
        total = sum(kind["total"] for kind in kinds.values())
        device, vram = self._device()
        exit_code = self._index.returncode if self._index is not None else None
        return {
            "t": "progress",
            "running": self._index is not None and exit_code is None,
            **({"exit": exit_code} if exit_code not in (None, 0) else {}),
            "done": done,
            "queued": total - done,
            "volume": pending_volume or volume,
            "volumes": volumes,
            "device": device,
            "vram_gb": vram,
            "kinds": kinds,
            "skipped": skipped,
            "failed": failed,
            "problems": problems,
            "tool_errors": [
                errors.tool_missing(count, tool, tools.TOOL_FEATURES[tool], tools.TOOLS[tool])
                .to_dict()
                for tool, count in sorted(missing.items())
            ],
        }
```

The volume, kind, page and OCR queries are the existing ones, moved under `if not code_index:`. `code.sqlite` therefore never shows up in `volumes` or `kinds`; it adds only to `failed` and `problems`. Do not open the store files with `os.open` here. Only `sqlite3.connect` may touch them, because closing a raw descriptor drops the reader's POSIX locks.

- [ ] **Step 9: Run the targeted tests**

Run the Step 2 command again. Expected: all pass.

- [ ] **Step 10: Run the full checks**

```bash
uv run --project helper pytest -q
node --test "tests/js/*.test.mjs"
uv run --project helper ruff check helper tests bin/omafind scripts evals
scripts/qmllint.sh
git diff --check
```

Expected: all green (integration run after Tasks 1-4: `1039 passed`, JS `226` pass). No QML or JS changes in this task.

- [ ] **Step 11: Commit**

```bash
git add helper/omafindd/failures.py helper/omafindd/extractors.py helper/omafindd/jobs.py \
  helper/omafindd/store.py helper/omafindd/code.py helper/omafindd/tools.py \
  helper/omafindd/setup.py tests/helper/test_failures.py tests/helper/test_jobs.py \
  tests/helper/test_ipc_setup.py tests/helper/test_code.py tests/helper/test_extract_pdf.py \
  tests/helper/test_ocr.py tests/helper/test_audio.py tests/helper/test_video.py \
  tests/helper/test_store.py tests/helper/test_tools.py
git status --short
git diff --staged --stat
git commit -S -m "fix(omafindd): name per-file failures and missing tools"
```

---

### Task 6: UI core: one error card, per-surface errors and the step 1 labels

**Files:**
- Create: `lib/errors.js`, `ui/ErrorCard.qml`, `tests/js/errors.test.mjs`, `tests/js/serviceErrors.test.mjs`
- Modify (line ranges verified against `4925220`; Tasks 1 to 5 do not touch these files):
  - `Service.qml`: imports 5-8, properties 27-74, signals 83-96, `warm` 93-96, `startIndexing` 117-127, `scanDrive` 141-145, `runUpdate` 197-201, request one-liners 206-212, `scan` 209-213, `installHelper` 237-241, `getBinds` 244-249, `receive` cases 330-395, `receiveSetupError` 439-458 (replaced, plus four new helpers after it), `receiveCounts` 490-494, `receiveState` 515-519, `helperSetup` 562-582
  - `lib/setup.js`: 4-7, `engineButton` 66-70, `serverTask` 77-87 (plus new `buildFailed`), `modelTask` 92-103, `fileLines` 108-118, `engineHint` 123-129
  - `ui/Banner.qml`: whole file (96 lines) becomes a wrapper over `ErrorCard`
  - `ui/SetupEngine.qml`: 22-25, 30-33, 43-47, 135-138 (card under the task rows), 158-165, 179-187
  - `SetupView.qml`: 23-29, 65-69, 119-123
  - Minimal adapters so nothing renders `[object Object]` until Task 7: `ui/SetupFolders.qml` 198-205, `ui/SetupIndex.qml` 26-30 and 213-217, `ui/DriveDialog.qml` 39-43, `ui/PathField.qml` 2-5 and 28-32, `SearchView.qml` 47-59 and 433-455
- Test: `tests/js/errors.test.mjs`, `tests/js/serviceErrors.test.mjs` (new); `tests/js/setup.test.mjs` 28-58 and appended tests; `tests/js/serviceDiscovery.test.mjs` 8-12; `tests/js/shortcutSetup.test.mjs` 17-37, 82-86, 100-104; `tests/js/discoveryLifecycle.test.mjs` 24-55

Decisions, one line each:
- `Banner.qml` becomes a 20-line `ErrorCard` wrapper that keeps its `lead`/`tokens`/`text`/`action`/`triggered()` API: SearchView's two banners need no change to get the card look, and the disk banner keeps its fact-token form.
- `walks[root].error` and `childFolders[path].error` stay strings (the error's title, `""` when none) because they render as one `error` fact token in folder rows and in `Setup.scanFacts`/`walkError`; a walk's full object also lands in `folderError`.
- A failed `shell.json` save in `startIndexing` goes to `folderError` (setup) or `driveError` (drive dialog), as Task 7 expects. `index_start` replies and the index exit broadcast go to `indexError`.
- An `error` reply whose `for` names no known surface lands in `engineError`, so no failure is dropped.
- Starting an action clears its own surface: `runtimeInstall` and `installHelper` clear `engineError`, `scan` clears `folderError`, `startIndexing` clears `indexError`, `scanDrive` clears `driveError` (tested in `serviceErrors.test.mjs`).
- `buildTime` keeps the canvas format (`Built in 3 min 12 s`, board Setup); the spec table's `3m 05s` reads as an example value.
- The paused footer keeps the running hint ("You can close this. Installing keeps going."); the spec table says "as now".
- When the build is already done and the model is not, the hint before start reads "Install downloads the model (865 MB)." (no build to announce).

**Interfaces:**

Consumes:
- Task 1/2 error object `{code, title, detail, fix?, log?}`; `{"t":"error","for":...}` with the object's fields at the top level; `runtime_progress.error`; `warm_failed.error`; `results.degraded` (object); `discover_counts.error`, `discover_children.error`, `fs_list.error` (objects); the index exit broadcast `{"t":"error","for":"index_start",...}`.
- Task 3: `bin/omafind setup --json` prints `{"ok": true}` or `{"ok": false, "error": {...}}` as its last stdout line.
- Task 5: the `retry_failed {"code": ...}` request. The `{"t":"retry_failed",...}` reply is not read here.

Produces (Task 7 relies on these names):
- `lib/errors.js` (`.pragma library`): `wrap(value)`, `from(message)`, `tone(code)`, `installCommand(fix)`, `offline(logPath)`, `hasRetry(error)`, `hasInstall(error)`. `from` takes the error out of any daemon message (top-level fields beside `t`/`for`/`seq`/`id`, an `error` field, or a bare `reason`) and drops the routing fields. `tone` returns `"warn"` for `server-starting`, `embedding-unavailable`, `disk-low`, `index-running` and `update-running`.
- `ui/ErrorCard.qml`: `property var error` (hidden while null), `bool retryHere: false`, `string retryText: "Retry"`, `bool compact: false`, `bool focusable: false`, `string tone` (defaults to `Errors.tone(error.code)`), `var tokens: []`, read-only state `installing`. `signal retry()`. Child objectNames are `<objectName>Install`, `<objectName>Log`, `<objectName>Retry` and `<objectName>Copy`. `installing` resets only when `error.code` changes, `error` becomes null, Retry is pressed, the poll succeeds or the card is destroyed, so a progress update that resends the same `tool_errors` object keeps the poll running. While installing, "Install packages" stays visible and pressable (it opens the terminal again) next to the spinner. With `retryHere`, Retry shows for a retry fix and for an install fix (whose detail says "then press Retry"). `stopInstalling()` is public: a view whose own Retry runs the same step calls it first (`SetupEngine.runEngine` does).
- `ui/Banner.qml`: same API as before (`lead`, `tokens`, `text`, `action`, `triggered()`), drawn by `ErrorCard` in the yellow tone.
- `Service.qml`: `searchError` (replaces `warmFailure`), `engineError`, `folderError` (replaces `discoverError`), `indexError`, `driveError`, `bindsError`. Each is an error object or null. `setupError` and `updateLine` are removed. Functions: `retryFailed(code)`, `errorSurface(kind, driveScan)`, `errorText(value)`, `helperFailure(stdout, stderr)`, `lastLine(text)`. Signals: `warmFailed(var error)` and `setupFailed(string forType, var error)`. `results.degraded` arrives already wrapped (object or null). The `setup-exited` update event now also carries `error`.
- `lib/setup.js`: `BUILD_MINUTES`, `buildFailed(rp)`, and the step 1 labels in `serverTask`, `modelTask`, `fileLines`, `engineHint` and `engineButton`.
- `ui/SetupEngine.qml`: `extraHeight` (SetupView adds it to the step 1 panel). The card's objectName is `omafindEngineError`.

- [ ] **Step 1: Write the failing tests**

Create `tests/js/errors.test.mjs`:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
import { plain, freeze } from './fixtures.mjs';
const e = load('errors.js');

const missing = freeze({ code: 'build-missing-packages', title: 'The search engine could not be built.',
  detail: 'Missing build packages: vulkan-headers. Install them, then press Retry.',
  fix: { kind: 'install', packages: ['vulkan-headers'] },
  log: '/home/u/.local/share/omafind/cache/logs/build-runtime.log' });

test('wrap keeps error objects and turns an older bare reason into an unknown error', () => {
  assert.equal(e.wrap(missing), missing);
  assert.deepEqual(plain(e.wrap('Embedding server failed to start')),
    { code: 'unknown', title: 'Embedding server failed to start', detail: '' });
  assert.deepEqual(plain(e.wrap('  Cannot read binds.\n')), { code: 'unknown', title: 'Cannot read binds.', detail: '' });
  for (const empty of [null, undefined, '', '   ', 0, false]) assert.equal(e.wrap(empty), null);
});

test('from takes the error out of any daemon message and drops its routing fields', () => {
  const { t, ...fields } = { t: 'error', ...missing };
  assert.deepEqual(plain(e.from({ t: 'error', for: 'runtime_install', ...fields })), plain(missing));
  assert.deepEqual(plain(e.from({ t: 'error', seq: 4, code: 'no-index', title: 'Nothing is indexed yet.',
    detail: 'Open setup and start the first index.' })),
    { code: 'no-index', title: 'Nothing is indexed yet.', detail: 'Open setup and start the first index.' });
  assert.deepEqual(plain(e.from({ t: 'open_failed', id: 'pdf:1', error: { code: 'file-missing',
    title: 'a.pdf is missing.', detail: 'It was moved or deleted after it was indexed.' } })),
    { code: 'file-missing', title: 'a.pdf is missing.', detail: 'It was moved or deleted after it was indexed.' });
  assert.deepEqual(plain(e.from({ t: 'runtime_progress', state: 'failed', error: null, reason: 'exit 1' })),
    { code: 'unknown', title: 'exit 1', detail: '' });
  assert.deepEqual(plain(e.from({ t: 'warm_failed', error: 'Vulkan device lost' })),
    { code: 'unknown', title: 'Vulkan device lost', detail: '' });
  assert.equal(e.from({ t: 'discover_children', path: '/h', dirs: [], error: null }), null);
  for (const empty of [null, undefined, '']) assert.equal(e.from(empty), null);
});

test('degraded and paused codes are yellow and every other code is red', () => {
  for (const code of ['server-starting', 'embedding-unavailable', 'disk-low', 'index-running', 'update-running'])
    assert.equal(e.tone(code), 'warn', code);
  for (const code of ['build-missing-packages', 'build-failed', 'server-start-failed', 'index-exited',
    'tool-missing', 'daemon-offline', 'unknown', '', undefined])
    assert.equal(e.tone(code), 'urgent', String(code));
});

test('an install fix becomes one pacman line', () => {
  assert.equal(e.installCommand(missing.fix), 'sudo pacman -S --needed vulkan-headers');
  assert.equal(e.installCommand({ kind: 'install', packages: ['fd', 'ripgrep'] }), 'sudo pacman -S --needed fd ripgrep');
  for (const fix of [{ kind: 'retry' }, { kind: 'install', packages: [] }, null, undefined])
    assert.equal(e.installCommand(fix), '');
});

test('fix helpers read the fix kind', () => {
  assert.equal(e.hasInstall(missing), true);
  assert.equal(e.hasRetry(missing), false);
  assert.equal(e.hasRetry({ code: 'build-failed', fix: { kind: 'retry' } }), true);
  assert.equal(e.hasInstall({ code: 'tools-missing', fix: { kind: 'install', packages: [] } }), false);
  for (const none of [null, undefined, { code: 'no-index', title: 'Nothing is indexed yet.', detail: '' }]) {
    assert.equal(e.hasInstall(none), false);
    assert.equal(e.hasRetry(none), false);
  }
});

test('the offline error offers Retry and links the startup log only when it exists', () => {
  assert.deepEqual(plain(e.offline()), { code: 'daemon-offline', title: 'The omafind service is not running.',
    detail: 'It did not answer on its socket. Press Retry to start it.', fix: { kind: 'retry' } });
  assert.equal(e.offline('/d/cache/logs/omafindd-start.log').log, '/d/cache/logs/omafindd-start.log');
  assert.equal(e.hasRetry(e.offline()), true);
});

test('copy written in the UI follows the copy rules', () => {
  const banned = /[–—!]|\b(seamless|leverage|robust|comprehensive|delve|showcase|vibrant|crucial|pivotal|streamline|empower|foster|testament|landscape|tapestry|journey|unlock|elevate)\b|bin\/omafind|systemctl|journalctl/i;
  const { title, detail } = e.offline();
  for (const line of [title, detail]) {
    assert.match(line, /\.$/);
    assert.doesNotMatch(line, banned);
  }
});
```

Create `tests/js/serviceErrors.test.mjs`:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { load } from './load.mjs';

const plain = value => JSON.parse(JSON.stringify(value));

function service(values = {}) {
  const sent = [];
  const ctx = vm.createContext({
    walks: {}, childFolders: {}, childrenAsked: {}, discoverCounts: {}, datasets: {}, repos: {}, worktrees: {},
    scanning: false, driveScanning: false, bindsReady: true, results: null, runtimeProgress: null,
    engineError: null, folderError: null, indexError: null, driveError: null, searchError: null, bindsError: null,
    Protocol: { decode: JSON.parse }, Errors: load('errors.js'),
    setupFailed() {}, warmFailed() {}, resultsReceived() {}, childrenReceived() {},
  });
  const source = readFileSync(new URL('../../Service.qml', import.meta.url), 'utf8');
  for (const match of source.matchAll(/^  function \w+\([^]*?^  \}/gm)) vm.runInContext(match[0], ctx);
  ctx.send = message => { sent.push(message); return true; };
  Object.assign(ctx, values);
  ctx.root = ctx;
  ctx.sent = sent;
  return ctx;
}

const scanFailed = { code: 'scan-failed', title: 'Pictures could not be scanned.',
  detail: 'Permission denied. Press Retry to scan it again.', fix: { kind: 'retry' } };

test('setup errors land on the surface of the request named in for', () => {
  const ctx = service({ scanning: true });
  for (const [kind, surface] of [['runtime_install', 'engineError'], ['runtime_status', 'engineError'],
    ['discover_start', 'folderError'], ['discover_children', 'folderError'], ['fs_list', 'folderError'],
    ['index_start', 'indexError'], ['retry_failed', 'indexError'], ['drive_decision', 'driveError'],
    ['binds_get', 'bindsError']]) {
    ctx.receive(JSON.stringify({ t: 'error', for: kind, ...scanFailed }));
    assert.deepEqual(plain(ctx[surface]), scanFailed, kind);
  }
  assert.equal(ctx.scanning, false);
  assert.equal(ctx.bindsReady, false);
});

test('a failed discover_start goes to the drive dialog while a drive scan runs', () => {
  const ctx = service({ driveScanning: true });
  ctx.receive(JSON.stringify({ t: 'error', for: 'discover_start', code: 'drive-not-mounted',
    title: 'Photos2024 is not connected.', detail: 'Connect it, then press Retry.', fix: { kind: 'retry' } }));
  assert.equal(ctx.driveError.code, 'drive-not-mounted');
  assert.equal(ctx.folderError, null);
  assert.equal(ctx.driveScanning, false);
});

test('the error object keeps its log and an older reason still shows', () => {
  const ctx = service();
  ctx.receive(JSON.stringify({ t: 'error', for: 'index_start', code: 'index-exited', title: 'Indexing stopped.',
    detail: 'The indexer exited with code 2. Open the log for the cause, then press Retry.',
    fix: { kind: 'retry' }, log: '/d/reindex.log' }));
  assert.equal(ctx.indexError.log, '/d/reindex.log');
  ctx.receive(JSON.stringify({ t: 'error', for: 'index_start', code: 'runtime-failed', reason: 'No folders are selected.' }));
  assert.deepEqual(plain(ctx.indexError), { code: 'unknown', title: 'No folders are selected.', detail: '' });
});

test('runtime progress holds the engine error only while it reads failed', () => {
  const ctx = service();
  ctx.receive(JSON.stringify({ t: 'runtime_progress', state: 'failed', build: { state: 'failed' },
    error: { code: 'build-missing-packages', title: 'The search engine could not be built.',
      detail: 'Missing build packages: vulkan-headers. Install them, then press Retry.',
      fix: { kind: 'install', packages: ['vulkan-headers'] } } }));
  assert.equal(ctx.engineError.code, 'build-missing-packages');
  ctx.receive(JSON.stringify({ t: 'runtime_progress', state: 'running', error: null }));
  assert.equal(ctx.engineError, null);
  ctx.receive(JSON.stringify({ t: 'runtime_progress', state: 'failed', reason: 'The runtime build failed: exit 1.' }));
  assert.equal(ctx.engineError.title, 'The runtime build failed: exit 1.');
});

test('warm failures and degraded results arrive as error objects', () => {
  const ctx = service();
  ctx.receive(JSON.stringify({ t: 'warm_failed', error: { code: 'server-start-failed',
    title: 'The embedding server did not start.', detail: 'It exited with code 1. Showing keyword matches until it starts.',
    fix: { kind: 'retry' }, log: '/d/llama-server.log' } }));
  assert.equal(ctx.searchError.code, 'server-start-failed');
  ctx.warm();
  assert.equal(ctx.searchError, null);
  assert.deepEqual(plain(ctx.sent.at(-1)), { t: 'warm' });
  ctx.receive(JSON.stringify({ t: 'warm_failed', reason: 'Vulkan device lost' }));
  assert.equal(ctx.searchError.title, 'Vulkan device lost');
  ctx.receive(JSON.stringify({ t: 'results', seq: 1, items: [], degraded: 'indexing in progress' }));
  assert.deepEqual(plain(ctx.results.degraded), { code: 'unknown', title: 'indexing in progress', detail: '' });
  ctx.receive(JSON.stringify({ t: 'results', seq: 2, items: [], degraded: null }));
  assert.equal(ctx.results.degraded, null);
});

test('a failed helper install reads the json line, then stderr', () => {
  const ctx = service();
  const missing = { code: 'tools-missing', title: 'Some tools omafind needs are missing.',
    detail: 'Missing: fd. Install them, then press Retry.', fix: { kind: 'install', packages: ['fd'] } };
  assert.deepEqual(plain(ctx.helperFailure('syncing\n' + JSON.stringify({ ok: false, error: missing }) + '\n', 'warning\n')), missing);
  assert.deepEqual(plain(ctx.helperFailure('', 'uv: command not found\n\n')),
    { code: 'unknown', title: 'uv: command not found', detail: '' });
  assert.equal(ctx.helperFailure('{"ok": true}', '').title, 'The omafind helper could not be installed.');
});

test('walk and child errors keep one fact and give the folder step the object', () => {
  const ctx = service();
  ctx.receiveCounts({ root: '/h', counts: {}, done: true, error: scanFailed });
  assert.equal(ctx.walks['/h'].error, 'Pictures could not be scanned.');
  assert.equal(ctx.folderError.code, 'scan-failed');
  ctx.receive(JSON.stringify({ t: 'discover_children', path: '/h/a', dirs: [], error: scanFailed }));
  assert.equal(ctx.childFolders['/h/a'].error, 'Pictures could not be scanned.');
  ctx.receive(JSON.stringify({ t: 'discover_children', path: '/h/b', dirs: [], error: 'Permission denied' }));
  assert.equal(ctx.childFolders['/h/b'].error, 'Permission denied');
});

test('a folder save that fails reports on the surface that asked', () => {
  const ctx = service({ persist() { return false; }, indexTimer: { restart() {} } });
  assert.equal(ctx.startIndexing([], [], ''), false);
  assert.match(ctx.folderError.title, /press Start indexing again\.$/);
  assert.equal(ctx.indexError, null);
  assert.equal(ctx.startIndexing([], [], 'usb'), false);
  assert.match(ctx.driveError.title, /press Index this drive again\.$/);
});

test('binds offline and retry_failed requests', () => {
  const ctx = service();
  ctx.retryFailed('tool-missing');
  assert.deepEqual(plain(ctx.sent.at(-1)), { t: 'retry_failed', code: 'tool-missing' });
  ctx.send = () => false;
  ctx.getBinds();
  assert.equal(ctx.bindsError.code, 'daemon-offline');
});

test('starting an action clears the error on its own surface', () => {
  const ctx = service({ engineError: scanFailed, folderError: scanFailed, indexError: scanFailed,
    driveError: scanFailed, helperRunning: false, helperSetup: { running: false },
    persist: () => true, indexTimer: { restart() {} } });
  ctx.runtimeInstall();
  assert.equal(ctx.engineError, null);
  ctx.engineError = scanFailed;
  ctx.installHelper();
  assert.equal(ctx.engineError, null);
  ctx.scan();
  assert.equal(ctx.folderError, null);
  ctx.startIndexing(['~'], [], '');
  assert.equal(ctx.indexError, null);
  ctx.scanDrive('usb');
  assert.equal(ctx.driveError, null);
});
```

Apply to `tests/js/setup.test.mjs` (the step 1 table, one case per row, plus the hint's size and build constant):

```diff
--- a/tests/js/setup.test.mjs
+++ b/tests/js/setup.test.mjs
@@ -28,5 +28,5 @@ test('formatters use specified rounding and whole-name home prefixes', () => {
 });
 test('engine controls depend on runtime state and helper readiness', () => {
-  for (const [state,text,action,visible] of [['idle','Download','install',true],['running','Pause','pause',true],['paused','Resume','install',true],['failed','Resume','install',true],['done','Download','install',false]]) {
+  for (const [state,text,action,visible] of [['idle','Install','install',true],['running','Pause','pause',true],['paused','Resume','install',true],['failed','Retry','install',true],['done','Install','install',false]]) {
     assert.deepEqual(plain(s.engineButton({state},true)), {text,action,visible,enabled:true});
   }
@@ -35,6 +35,6 @@ test('engine controls depend on runtime state and helper readiness', () => {
   assert.equal(s.totalFraction({done:100,total:10}), 1);
   assert.equal(s.totalFraction(null), 0);
-  assert.equal(s.engineHint(runtime), 'You can close this. The download keeps going.');
-  assert.equal(s.engineHint({state:'failed',reason:'Try again.'}), 'Try again.');
+  assert.equal(s.engineHint(runtime), 'You can close this. Installing keeps going.');
+  assert.equal(s.engineHint({state:'failed',reason:'Try again.'}), '');
   assert.equal(s.engineHint({state:'done'}), 'Everything is installed. Folders are next.');
 });
@@ -42,7 +42,7 @@ test('model task uses progress facts and omits unknown time', () => {
   assert.deepEqual(values(s.modelTask(runtime).got), [['got','512/865 MB'],['left','~1 min']]);
   assert.deepEqual(values(s.modelTask({...runtime,left_seconds:null}).got), [['got','512/865 MB'],['verify','sha256']]);
-  assert.equal(s.modelTask({state:'done'}).value, 'Verified');
+  assert.equal(s.modelTask({state:'done'}).value, 'Installed');
   assert.equal(s.modelTask({state:'paused'}).value, 'Paused');
-  assert.equal(s.modelTask(null).value, 'Queued');
+  assert.equal(s.modelTask(null).value, 'Not downloaded');
 });
 test('helper and server tasks expose installation and build facts', () => {
@@ -54,5 +54,5 @@ test('helper and server tasks expose installation and build facts', () => {
   assert.equal(s.serverTask({state:'running',build:{state:'run',seconds:65}}).value, 'Building · 1 min 05 s');
   assert.equal(s.serverTask({state:'failed',build:{state:'failed'}}).mark, 'failed');
-  assert.equal(s.serverTask(null).value, 'Starting');
+  assert.equal(s.serverTask(null).value, 'Not installed');
 });
 test('file lines distinguish wait run verify and verified', () => {
@@ -156,2 +156,63 @@ test('folder errors trim tool prefixes and trailing punctuation and give a next
     'Could not list your folders: Connection lost. Press Back and try again.');
 });
+
+const idle = freeze({ ...plain(runtime), state: 'idle', step: null, file: null, done: 0, left_seconds: null,
+  build: { ...runtime.build, state: 'wait', seconds: null },
+  files: { model: { ...runtime.files.model, state: 'wait', done: 0 }, mmproj: { ...runtime.files.mmproj, state: 'wait', done: 0 } } });
+const building = freeze({ ...idle, state: 'running', step: 'build', build: { ...idle.build, state: 'run', seconds: 72 } });
+const failedBuild = freeze({ ...idle, state: 'failed', build: { ...idle.build, state: 'failed', seconds: 40 },
+  error: { code: 'build-missing-packages', title: 'The search engine could not be built.',
+    detail: 'Missing build packages: vulkan-headers. Install them, then press Retry.',
+    fix: { kind: 'install', packages: ['vulkan-headers'] } } });
+const failedDownload = freeze({ ...runtime, state: 'failed', left_seconds: null,
+  error: { code: 'model-download-failed', title: 'The model could not be downloaded.',
+    detail: 'HTTP 503. Check the network connection, then press Retry.', fix: { kind: 'retry' } } });
+const paused = freeze({ ...building, state: 'paused' });
+const installed = freeze({ ...runtime, state: 'done', step: null, file: null, done: 865, left_seconds: null,
+  build: { ...runtime.build, seconds: null },
+  files: { model: runtime.files.model, mmproj: { ...runtime.files.mmproj, state: 'ok', done: 555 } } });
+
+function stepOne(rp) {
+  const server = s.serverTask(rp), model = s.modelTask(rp), button = s.engineButton(rp, true);
+  return { server: server.value, serverMark: server.mark, model: model.value, modelMark: model.mark,
+    files: plain(s.fileLines(rp)).map(line => line.mb), hint: s.engineHint(rp),
+    button: button.text, action: button.action, visible: button.visible };
+}
+
+test('step 1 rows follow the labels table for each situation', () => {
+  const running = 'You can close this. Installing keeps going.';
+  for (const [name, rp, expected] of [
+    ['nothing pressed', idle, { server: 'Not installed', serverMark: 'wait', model: 'Not downloaded', modelMark: 'wait',
+      files: ['310 MB · not downloaded', '555 MB · not downloaded'],
+      hint: 'Install builds the server (about 3 min) and downloads the model (865 MB).',
+      button: 'Install', action: 'install', visible: true }],
+    ['building', building, { server: 'Building · 1 min 12 s', serverMark: 'run', model: 'Waiting', modelMark: 'wait',
+      files: ['310 MB · queued', '555 MB · queued'], hint: running, button: 'Pause', action: 'pause', visible: true }],
+    ['downloading', runtime, { server: 'Built in 3 min 12 s', serverMark: 'ok', model: null, modelMark: 'run',
+      files: ['310 MB · verified', '202 of 555 MB'], hint: running, button: 'Pause', action: 'pause', visible: true }],
+    ['build failed', failedBuild, { server: 'Failed', serverMark: 'failed', model: 'Not downloaded', modelMark: 'wait',
+      files: ['310 MB · not downloaded', '555 MB · not downloaded'], hint: '', button: 'Retry', action: 'install', visible: true }],
+    ['download failed', failedDownload, { server: 'Built in 3 min 12 s', serverMark: 'ok', model: 'Failed', modelMark: 'failed',
+      files: ['310 MB · verified', '202 of 555 MB'], hint: '', button: 'Retry', action: 'install', visible: true }],
+    ['paused', paused, { server: 'Paused', serverMark: 'wait', model: 'Paused', modelMark: 'wait',
+      files: ['310 MB · queued', '555 MB · queued'], hint: running, button: 'Resume', action: 'install', visible: true }],
+    ['done', installed, { server: 'Installed', serverMark: 'ok', model: 'Installed', modelMark: 'ok',
+      files: ['310 MB · verified', '555 MB · verified'], hint: 'Everything is installed. Folders are next.',
+      button: 'Install', action: 'install', visible: false }],
+  ]) assert.deepEqual(stepOne(rp), expected, name);
+});
+
+test('the step 1 hint takes the model size from the daemon and the build time from one constant', () => {
+  assert.equal(s.BUILD_MINUTES, 3);
+  assert.equal(s.engineHint(null), 'Install builds the server (about 3 min) and downloads the model.');
+  assert.equal(s.engineHint({ ...idle, total: 900 }), 'Install builds the server (about 3 min) and downloads the model (900 MB).');
+  assert.equal(s.engineHint({ ...idle, build: { ...idle.build, state: 'ok' } }), 'Install downloads the model (865 MB).');
+  assert.equal(s.serverTask({ ...idle, build: { ...idle.build, state: 'ok' } }).value, 'Installed');
+});
+
+test('a retried build shows Building, not the old failure', () => {
+  const retried = { ...failedBuild, state: 'running', step: null, error: null };
+  assert.equal(s.serverTask(retried).mark, 'run');
+  assert.match(s.serverTask(retried).value, /^Building/);
+  assert.equal(s.modelTask(retried).value, 'Waiting');
+});
```

The vm harnesses that evaluate `Service.qml` now need `Errors`, and the fakes switch to objects:

```diff
--- a/tests/js/serviceDiscovery.test.mjs
+++ b/tests/js/serviceDiscovery.test.mjs
@@ -8,5 +8,5 @@ function service(values = {}) {
   const ctx = vm.createContext({
     discoverCounts: {}, walks: {}, datasets: {}, repos: {}, worktrees: {}, childFolders: {}, childrenAsked: {},
-    Protocol: { decode: JSON.parse }, childrenReceived() {}, setupFailed() {},
+    Protocol: { decode: JSON.parse }, Errors: load('errors.js'), childrenReceived() {}, setupFailed() {},
     send() { return true; }, ...values,
   });
--- a/tests/js/shortcutSetup.test.mjs
+++ b/tests/js/shortcutSetup.test.mjs
@@ -17,5 +17,6 @@ test('Service requests live binds and routes replies and errors', () => {
   const sent = [];
   const { ctx } = functions('Service.qml', {
-    binds: [], bindsReady: true, bindsError: 'old', Protocol: { decode: JSON.parse },
+    binds: [], bindsReady: true, bindsError: { code: 'unknown', title: 'old', detail: '' }, driveScanning: false,
+    Protocol: { decode: JSON.parse }, Errors: load('errors.js'),
     send(message) { sent.push(message); return true; }, setupFailed() {},
   });
@@ -23,15 +24,19 @@ test('Service requests live binds and routes replies and errors', () => {
   assert.equal(sent[0].t, 'binds_get');
   assert.equal(ctx.bindsReady, false);
-  assert.equal(ctx.bindsError, '');
+  assert.equal(ctx.bindsError, null);
   ctx.receive(JSON.stringify({ t: 'binds', binds: [{ chord: 'F9', description: 'Menu' }] }));
   assert.equal(ctx.bindsReady, true);
   assert.equal(ctx.binds[0].chord, 'F9');
   ctx.getBinds();
-  ctx.receive(JSON.stringify({ t: 'error', for: 'binds_get', reason: 'Cannot read binds.' }));
+  ctx.receive(JSON.stringify({ t: 'error', for: 'binds_get', code: 'binds-failed',
+    title: 'Your Hyprland bindings could not be read.', detail: 'Hyprland is not running. The shortcut was not saved.',
+    fix: { kind: 'retry' } }));
   assert.equal(ctx.bindsReady, false);
-  assert.equal(ctx.bindsError, 'Cannot read binds.');
+  assert.equal(ctx.bindsError.code, 'binds-failed');
+  ctx.receive(JSON.stringify({ t: 'error', for: 'binds_get', reason: 'Cannot read binds.' }));
+  assert.equal(ctx.bindsError.title, 'Cannot read binds.');
   ctx.send = () => false;
   ctx.getBinds();
-  assert.match(ctx.bindsError, /not running/);
+  assert.match(ctx.bindsError.title, /not running/);
 });

@@ -82,5 +87,5 @@ function index(values = {}) {
   const { ctx, source } = functions('ui/SetupIndex.qml', {
     chosen: 'F9', saving: false, Keycombo: load('keycombo.js'),
-    service: { binds: [], bindsReady: true, bindsError: '' },
+    service: { binds: [], bindsReady: true, bindsError: null },
     recorder: { active: false, operation: '', pendingLeave: false, conflict: '', lost: false, exposed: false },
     ...values,
@@ -100,5 +105,5 @@ test('saving allows unknown binds after an error but waits for cleanup', () => {
   ctx.service.bindsReady = false;
   assert.equal(saveEnabled(), false);
-  ctx.service.bindsError = 'Could not read bindings.';
+  ctx.service.bindsError = { code: 'binds-failed', title: 'Your Hyprland bindings could not be read.', detail: '' };
   assert.equal(saveEnabled(), true);
   assert.match(rowValue('note'), /not been checked for conflicts/);
--- a/tests/js/discoveryLifecycle.test.mjs
+++ b/tests/js/discoveryLifecycle.test.mjs
@@ -24,5 +24,5 @@ test('reopening setup reuses or restarts discovery despite a cached first level'
   let scans = 0;
   const ctx = functions('SetupView.qml', { back: false, step: 2, walkError: '',
-    service: { discover: { folders: [] }, discoverError: '', scanning: false,
+    service: { discover: { folders: [] }, folderError: null, scanning: false,
       scan() { scans++; } } });
   ctx.reset();
@@ -34,5 +34,5 @@ test('a reconnected Folders step requests a fresh discovery snapshot', () => {
   let scans = 0;
   const ctx = functions('SetupView.qml', { visible: true, step: 2, walkError: '',
-    service: { ready: true, discover: { folders: [] }, discoverError: '', scanning: false,
+    service: { ready: true, discover: { folders: [] }, folderError: null, scanning: false,
       scan() { scans++; } } });
   const source = readFileSync(new URL('../../SetupView.qml', import.meta.url), 'utf8');
@@ -51,5 +51,5 @@ test('Back then Next retries a failed background walk', () => {
   let scans = 0;
   const ctx = functions('SetupView.qml', { back: true, walkError: 'fd failed: Permission denied',
-    service: { discover: { folders: [] }, discoverError: '', scanning: false,
+    service: { discover: { folders: [] }, folderError: null, scanning: false,
       scan() { scans++; } } });
   ctx.showFolders();
```

- [ ] **Step 2: Run them to see them fail**

```bash
node --test tests/js/errors.test.mjs tests/js/serviceErrors.test.mjs tests/js/setup.test.mjs tests/js/serviceDiscovery.test.mjs tests/js/shortcutSetup.test.mjs
```

Expected: `errors.test.mjs`, `serviceErrors.test.mjs`, `serviceDiscovery.test.mjs` and `shortcutSetup.test.mjs` fail at load with `ENOENT: no such file or directory, open '.../lib/errors.js'`. `setup.test.mjs` fails on `'Download' !== 'Install'`, `'Starting' !== 'Not installed'`, `'Verified' !== 'Installed'` and on every row of `step 1 rows follow the labels table for each situation`.

- [ ] **Step 3: Add `lib/errors.js`**

```js
.pragma library

// Degraded and paused states that recover by themselves; every other code is a failure.
var WARN_CODES = ["server-starting", "embedding-unavailable", "disk-low", "index-running", "update-running"]

// An error object passes through. An older daemon's bare `reason` string becomes an `unknown` error.
function wrap(value) {
  if (value && typeof value === "object") return value
  if (typeof value === "string" && value.trim() !== "") return {code: "unknown", title: value.trim(), detail: ""}
  return null
}

// The error a daemon message carries: a `t:"error"` reply with the fields beside `t`, `for`, `seq` or
// `id`, an `error` field, or an older daemon's bare `reason`. Routing fields are left out.
function from(message) {
  if (!message || typeof message !== "object") return wrap(message)
  if (message.error !== undefined && message.error !== null) return from(message.error)
  if (typeof message.title !== "string") return wrap(message.reason)
  var error = {code: message.code || "unknown", title: message.title, detail: message.detail || ""}
  if (message.fix) error.fix = message.fix
  if (message.log) error.log = message.log
  return error
}

function tone(code) {
  return WARN_CODES.indexOf(code) >= 0 ? "warn" : "urgent"
}

function hasInstall(error) {
  return !!(error && error.fix && error.fix.kind === "install" && Array.isArray(error.fix.packages)
    && error.fix.packages.length > 0)
}

function hasRetry(error) {
  return !!(error && error.fix && error.fix.kind === "retry")
}

// The line to paste instead of pressing Install packages.
function installCommand(fix) {
  return hasInstall({fix: fix}) ? "sudo pacman -S --needed " + fix.packages.join(" ") : ""
}

// The socket did not answer. `logPath` is the daemon's startup log when that file exists.
function offline(logPath) {
  return {code: "daemon-offline", title: "The omafind service is not running.",
    detail: "It did not answer on its socket. Press Retry to start it.", fix: {kind: "retry"},
    log: logPath || undefined}
}
```

- [ ] **Step 4: Step 1 labels in `lib/setup.js`**

```diff
--- a/lib/setup.js
+++ b/lib/setup.js
@@ -4,4 +4,6 @@ var KINDS = ["text", "pdf", "image", "video", "audio"]
 var KIND_LABELS = {text: "Text", pdf: "PDF", image: "Images", video: "Video", audio: "Audio"}
 var DATASET_KINDS = {image: "images", video: "videos", audio: "audio"}
+// The step 1 hint's build estimate, from the board's "Built in 3 min 12 s".
+var BUILD_MINUTES = 3

 function count(n) {
@@ -66,5 +68,5 @@ function stepLabel(current) {
 function engineButton(rp, helperReady) {
   var state = rp ? rp.state : "idle"
-  return {text: state === "running" ? "Pause" : state === "paused" || state === "failed" ? "Resume" : "Download",
+  return {text: state === "running" ? "Pause" : state === "paused" ? "Resume" : state === "failed" ? "Retry" : "Install",
     visible: state !== "done", enabled: !!helperReady, action: state === "running" ? "pause" : "install"}
 }
@@ -77,11 +79,17 @@ function helperTask(connection) {
 }

+// A run that failed before the server was built; the model was never asked for.
+function buildFailed(rp) {
+  return !!rp && rp.state === "failed" && !(rp.build && rp.build.state === "ok")
+}
+
 function serverTask(rp) {
   var build = rp && rp.build ? rp.build : {}
-  var mark = build.state === "ok" ? "ok" : build.state === "run" ? "run" : build.state === "failed" ? "failed" : "wait"
-  if (rp && rp.state === "paused" && mark === "run") mark = "wait"
+  var state = rp ? rp.state : "idle"
+  var mark = build.state === "ok" ? "ok" : state === "running" ? "run"
+    : build.state === "failed" || buildFailed(rp) ? "failed" : "wait"
   var value = mark === "ok" ? (build.seconds == null ? "Installed" : "Built in " + buildTime(build.seconds))
-    : mark === "failed" ? "Failed" : rp && rp.state === "paused" ? "Paused"
-    : mark === "run" ? "Building" + (build.seconds == null ? "" : " · " + buildTime(build.seconds)) : "Starting"
+    : mark === "failed" ? "Failed" : state === "paused" ? "Paused"
+    : mark === "run" ? "Building" + (build.seconds == null ? "" : " · " + buildTime(build.seconds)) : "Not installed"
   var tokens = [token("llama.cpp", build.tag || "b11461"), token("backend", build.backend || "Vulkan")]
   if (build.gpu) tokens.push(token("gpu", build.gpu))
@@ -92,4 +100,5 @@ function modelTask(rp) {
   var state = rp ? rp.state : "idle"
   var running = state === "running" && rp.step === "download"
+  var failed = state === "failed" && !buildFailed(rp)
   var got = null
   if (running) {
@@ -97,7 +106,8 @@ function modelTask(rp) {
     got.push(rp.left_seconds == null ? token("verify", "sha256") : token("left", approxMinutes(rp.left_seconds)))
   }
-  return {mark: state === "done" ? "ok" : state === "failed" ? "failed" : running ? "run" : "wait",
-    value: state === "done" ? "Verified" : state === "paused" ? "Paused" : state === "failed" ? "Failed" : running ? null : "Queued",
-    valueTone: state === "done" ? "ok" : state === "failed" ? "fail" : "plain",
+  return {mark: state === "done" ? "ok" : failed ? "failed" : running ? "run" : "wait",
+    value: state === "done" ? "Installed" : state === "paused" ? "Paused" : failed ? "Failed" : running ? null
+      : state === "running" ? "Waiting" : "Not downloaded",
+    valueTone: state === "done" ? "ok" : failed ? "fail" : "plain",
     tokens: [token("repo", "ggml-org/embeddinggemma-2-GGUF"), token("quant", "Q8_0"), token("license", "Apache 2.0"), token("verify", "sha256")], got: got}
 }
@@ -108,4 +118,5 @@ function fraction(done, total) {

 function fileLines(rp) {
+  var waiting = rp && (rp.state === "running" || rp.state === "paused") ? "queued" : "not downloaded"
   return ["model", "mmproj"].filter(function(key) { return rp && rp.files && rp.files[key] }).map(function(key) {
     var file = rp.files[key]
@@ -114,5 +125,5 @@ function fileLines(rp) {
     return {icon: done ? "✓" : active ? "↓" : "·", tone: done ? "ok" : active ? "accent" : "dim", name: file.name,
       mb: file.state === "run" ? file.done + " of " + file.total + " MB"
-        : file.total + " MB · " + (done ? "verified" : file.state === "verify" ? "checking sha256" : "queued"),
+        : file.total + " MB · " + (done ? "verified" : file.state === "verify" ? "checking sha256" : waiting),
       fraction: done ? 1 : fraction(file.done, file.total), done: done}
   })
@@ -123,7 +134,13 @@ function totalFraction(rp) {
 }

+// Failures show in the error card instead of the hint.
 function engineHint(rp) {
-  return rp && rp.reason ? rp.reason : engineReady(rp) ? "Everything is installed. Folders are next."
-    : "You can close this. The download keeps going."
+  var state = rp ? rp.state : "idle"
+  if (state === "failed") return ""
+  if (state === "done") return "Everything is installed. Folders are next."
+  if (state === "running" || state === "paused") return "You can close this. Installing keeps going."
+  var model = "the model" + (rp && rp.total ? " (" + rp.total + " " + (rp.unit || "MB") + ")" : "")
+  if (rp && rp.build && rp.build.state === "ok") return "Install downloads " + model + "."
+  return "Install builds the server (about " + BUILD_MINUTES + " min) and downloads " + model + "."
 }

```

- [ ] **Step 5: Per-surface errors in `Service.qml`**

```diff
diff --git a/Service.qml b/Service.qml
index 409ec77..c3b8238 100644
--- a/Service.qml
+++ b/Service.qml
@@ -4,6 +4,7 @@ import Quickshell.Io
 import "lib/Backoff.js" as Backoff
 import "lib/Protocol.js" as Protocol
 import "lib/Connection.js" as Connection
+import "lib/errors.js" as Errors
 import "lib/Settings.js" as Settings
 import "lib/Update.js" as Update
 import "lib/volumes.js" as Volumes
@@ -26,14 +27,15 @@ Item {
   property var results: null
   property var preview: null
   property var status: null
-  property string warmFailure: ""
+  // Each surface's latest failure: an error object (docs/ipc.md "Errors") or null.
+  property var searchError: null

   // Setup (issue #5). The shell entry, parsed from shell.json, and the latest daemon facts.
   property var settingsEntry: ({})
   readonly property var settings: Settings.normalize(settingsEntry)
   property var runtimeProgress: null
   property var discover: null
-  property string discoverError: ""
+  property var folderError: null
   property bool scanning: false
   // Absolute folder -> rolled-up counts, merged from every discover_counts batch.
   property var discoverCounts: ({})
@@ -51,15 +53,15 @@ Item {
   property bool indexPending: false
   property var binds: []
   property bool bindsReady: false
-  property string bindsError: ""
-  property string setupError: ""
+  property var bindsError: null
+  property var engineError: null
+  property var indexError: null
   property bool helperRunning: false
   // Issue #16: the lib/Update.js state. `updateRun` marks a helperSetup run started by an update;
   // `updateQueued` holds one back while a setup the user started is still running.
   property var update: Update.initial()
   property bool updateRun: false
   property bool updateQueued: false
-  property string updateLine: ""
   property bool runtimeAsked: false
   property string indexVolume: ""

@@ -69,7 +71,7 @@ Item {
   property real clock: Date.now()
   property var driveDiscover: null
   property bool driveScanning: false
-  property string driveError: ""
+  property var driveError: null
   readonly property var ignoredVolumes: Array.isArray(settings.ignoredVolumes) ? settings.ignoredVolumes
     : Array.isArray(settingsEntry.ignoredVolumes) ? settingsEntry.ignoredVolumes.filter(uuid => typeof uuid === "string" && uuid !== "")
     : []
@@ -82,16 +84,16 @@ Item {
   signal itemFailed(var reply)
   signal itemOpened(var reply)
   signal openFailed(var reply)
-  signal warmFailed(string reason)
+  signal warmFailed(var error)
   signal statusReceived(var reply)
   signal childrenReceived(string path)
   signal fsListReceived(var reply)
-  signal setupFailed(string forType, string reason)
+  signal setupFailed(string forType, var error)
   // A reconciled drive changed what a search can find.
   signal volumesRefreshed()

   function warm() {
-    warmFailure = ""
+    searchError = null
     return send({t: "warm"})
   }

@@ -116,13 +118,16 @@ Item {
   // off-thread write to land in shell.json (or 2 s, whichever comes first). A drive passes its
   // volume UUID and saves only the roots, so setup state stays as it was.
   function startIndexing(roots, codeRoots, volume) {
-    setupError = ""
+    indexError = null
+    if (volume) driveError = null
     var changes = volume ? {roots: roots} : {roots: roots, codeRoots: codeRoots, setupDone: true}
     if (volume && Array.isArray(codeRoots)) changes.codeRoots = codeRoots
     if (!persist(changes)) {
-      setupError = volume
+      var failure = Errors.wrap(volume
         ? "Could not save the folders to shell.json. Check that the omafind plugin is enabled, then press Index this drive again."
-        : "Could not save the folders to shell.json. Check that the omafind plugin is enabled, then press Start indexing again."
+        : "Could not save the folders to shell.json. Check that the omafind plugin is enabled, then press Start indexing again.")
+      if (volume) driveError = failure
+      else folderError = failure
       return false
     }
     indexVolume = volume || ""
@@ -140,7 +145,7 @@ Item {
   }

   function scanDrive(uuid) {
-    driveError = ""
+    driveError = null
     driveDiscover = null
     driveScanning = send({t: "discover_start", volume: uuid})
     return driveScanning
@@ -196,18 +201,21 @@ Item {
       return
     }
     updateRun = true
-    updateLine = ""
     helperRunning = true
     helperSetup.running = true
   }

-  function runtimeInstall() { return send({t: "runtime_install"}) }
+  function runtimeInstall() {
+    engineError = null
+    return send({t: "runtime_install"})
+  }
   function runtimePause() { return send({t: "runtime_pause"}) }
   function requestRuntimeStatus() { return send({t: "runtime_status"}) }
   function requestProgress() { return send({t: "index_progress"}) }
+  function retryFailed(code) { return send({t: "retry_failed", code: code}) }

   function scan() {
-    discoverError = ""
+    folderError = null
     scanning = send({t: "discover_start"})
     return scanning
   }
@@ -236,15 +244,15 @@ Item {
   // Port of omaone's runSetup: bin/omafind setup installs the venv and enables the unit.
   function installHelper() {
     if (helperRunning) return
-    setupError = ""
+    engineError = null
     helperRunning = true
     helperSetup.running = true
   }

   function getBinds() {
     bindsReady = false
-    bindsError = ""
-    if (!send({t: "binds_get"})) bindsError = "omafindd is not running."
+    bindsError = null
+    if (!send({t: "binds_get"})) bindsError = Errors.offline()
   }

   function saveShortcut(chord, menuRow, done) {
@@ -329,6 +337,7 @@ Item {
       receiveState(message)
       break
     case "results":
+      message.degraded = Errors.wrap(message.degraded)
       results = message
       resultsReceived(message)
       break
@@ -356,8 +365,8 @@ Item {
       openFailed(message)
       break
     case "warm_failed":
-      warmFailure = typeof message.reason === "string" ? message.reason : ""
-      warmFailed(warmFailure)
+      searchError = Errors.from(message)
+      warmFailed(searchError)
       break
     case "status":
       status = message
@@ -366,21 +375,22 @@ Item {
     case "binds":
       binds = Array.isArray(message.binds) ? message.binds : []
       bindsReady = true
-      bindsError = ""
+      bindsError = null
       break
     case "runtime_progress":
       runtimeProgress = message
+      engineError = message.state === "failed" ? Errors.from(message) : null
       break
     case "discover_result":
       if (Array.isArray(message.roots)) message.roots.forEach(entry => clearDiscovery(entry.path))
       if (message.volume) {
         driveScanning = false
-        driveError = ""
+        driveError = null
         driveDiscover = message
         break
       }
       scanning = false
-      discoverError = ""
+      folderError = null
       discover = message
       break
     case "discover_counts":
@@ -390,7 +400,7 @@ Item {
       var nextChildren = Object.assign({}, childFolders)
       nextChildren[message.path] = {dirs: Array.isArray(message.dirs) ? message.dirs : [],
         volume: typeof message.volume === "string" ? message.volume : "",
-        error: typeof message.error === "string" ? message.error : ""}
+        error: errorText(message.error)}
       childFolders = nextChildren
       var childCounts = Object.assign({}, discoverCounts)
       nextChildren[message.path].dirs.forEach(dir => { if (dir.counts && !childCounts[dir.path]) childCounts[dir.path] = dir.counts })
@@ -438,22 +448,62 @@ Item {
   }

   function receiveSetupError(message) {
-    var reason = typeof message.reason === "string" ? message.reason : ""
-    // Errors carry no volume, so a failed discover_start is the drive scan's while one runs.
-    if (message.for === "discover_start" && driveScanning) {
-      driveScanning = false
-      driveError = reason
-    } else if (message.for === "discover_start") {
-      scanning = false
-      discoverError = reason
-    } else if (message.for === "binds_get") {
-      bindsReady = false
-      bindsError = reason
-    } else {
-      setupError = reason
+    var error = Errors.from(message)
+    var surface = errorSurface(message.for, driveScanning)
+    if (message.for === "discover_start") {
+      if (driveScanning) driveScanning = false
+      else scanning = false
     }
+    if (message.for === "binds_get") bindsReady = false
     if (message.for === "discover_children") childrenAsked = {}
-    setupFailed(message.for, reason)
+    root[surface] = error
+    setupFailed(message.for, error)
+  }
+
+  // Each request reports on one surface. Requests with no surface of their own report on step 1.
+  // Errors carry no volume, so a failed discover_start is the drive scan's while one runs.
+  function errorSurface(kind, driveScan) {
+    switch (kind) {
+    case "discover_start":
+      return driveScan ? "driveError" : "folderError"
+    case "discover_stop":
+    case "discover_children":
+    case "fs_list":
+      return "folderError"
+    case "drive_decision":
+      return "driveError"
+    case "binds_get":
+      return "bindsError"
+    case "index_start":
+    case "index_progress":
+    case "retry_failed":
+      return "indexError"
+    default:
+      return "engineError"
+    }
+  }
+
+  // Walks and folder rows show a failure as one fact: the error's title.
+  function errorText(value) {
+    var error = Errors.wrap(value)
+    return error ? error.title : ""
+  }
+
+  // `bin/omafind setup --json` ends stdout with {"ok": false, "error": {...}}; stderr is the fallback.
+  function helperFailure(stdout, stderr) {
+    var reply = null
+    try {
+      reply = JSON.parse(lastLine(stdout))
+    } catch (error) {
+      reply = null
+    }
+    if (reply && reply.ok === false && reply.error) return Errors.wrap(reply.error)
+    return Errors.wrap(lastLine(stderr) || "The omafind helper could not be installed.")
+  }
+
+  function lastLine(text) {
+    var lines = String(text || "").split("\n").map(line => line.trim()).filter(line => line !== "")
+    return lines.length ? lines[lines.length - 1] : ""
   }

   // Clears counts, datasets and walks under `walkRoot`. Cached children stay: they hold the folder
@@ -489,7 +539,8 @@ Item {
     discoverCounts = counts
     var nextWalks = Object.assign({}, walks)
     nextWalks[message.root] = {done: !!message.done, seconds: typeof message.seconds === "number" ? message.seconds : null,
-      error: typeof message.error === "string" ? message.error : ""}
+      error: errorText(message.error)}
+    if (message.error) folderError = Errors.wrap(message.error)
     if (Array.isArray(message.datasets)) {
       var nextSets = Object.assign({}, datasets)
       message.datasets.forEach(entry => nextSets[entry.path] = entry)
@@ -514,7 +565,7 @@ Item {
         || ["stopped", "text", "full"].indexOf(message.embedder) === -1) return
     daemonState = message
     reduceUpdate({type: "daemon", build: typeof message.build === "string" ? message.build : ""})
-    if (message.embedder !== "stopped") warmFailure = ""
+    if (message.embedder !== "stopped") searchError = null
     connection = Connection.reduce(connection, {type: "state"})
     if (ready && !runtimeProgress && !runtimeAsked) runtimeAsked = requestRuntimeStatus()
   }
@@ -561,23 +612,18 @@ Item {

   Process {
     id: helperSetup
-    command: [root.pluginDir + "/bin/omafind", "setup"]
-    stderr: SplitParser {
-      splitMarker: "\n"
-      onRead: data => {
-        if (!data.trim()) return
-        if (root.updateRun) root.updateLine = data.trim()
-        else root.setupError = data.trim()
-      }
-    }
+    command: [root.pluginDir + "/bin/omafind", "setup", "--json"]
+    stdout: StdioCollector { id: helperOut; waitForEnd: true }
+    stderr: StdioCollector { id: helperErr; waitForEnd: true }
     onExited: (exitCode, exitStatus) => {
       var ok = exitCode === 0 && exitStatus === 0
+      var failure = ok ? null : root.helperFailure(helperOut.text, helperErr.text)
       root.helperRunning = false
       if (root.updateRun) {
         root.updateRun = false
-        root.reduceUpdate({type: "setup-exited", ok: ok, line: root.updateLine})
-      } else if (ok) {
-        root.setupError = ""
+        root.reduceUpdate({type: "setup-exited", ok: ok, line: root.lastLine(helperErr.text), error: failure})
+      } else {
+        root.engineError = failure
       }
       if (root.updateQueued) {
         root.updateQueued = false
```

Readers of the removed names: `setupError` was read by `SetupView.qml:27`, `ui/SetupFolders.qml:200,203` and `ui/DriveDialog.qml:41`. `discoverError` was read by `SetupView.qml:67,121`. `bindsError` (now an object) is read by `ui/SetupIndex.qml:28,215`. `driveError` is read by `ui/DriveDialog.qml:41`. `warmFailure` was read by `SearchView.qml:50`. Step 8 updates each of them. No QML connects to `warmFailed` or `setupFailed`; only the test stubs name them.

- [ ] **Step 6: Add `ui/ErrorCard.qml` and make `ui/Banner.qml` a wrapper**

`ui/ErrorCard.qml`:

```qml
import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import ".." as Plugin
import "../lib/errors.js" as Errors

// One failure in the anatomy of `.ban`: a glyph, the bold title, the detail and the fix buttons on
// the right. `error` is an error object (docs/ipc.md "Errors"); the card hides while it is null.
Rectangle {
  id: root

  property var error: null
  // Views with a primary control of their own (the setup footer) leave the card's Retry off.
  property bool retryHere: false
  property string retryText: "Retry"
  // Toasts and the preview pane: no pacman line and at most two lines of detail.
  property bool compact: false
  property bool focusable: false
  property string tone: Errors.tone(error ? error.code : "")
  // Fact tokens after the title (the disk banner).
  property var tokens: []
  property bool installing: false
  property int waited: 0

  // The Retry button was pressed, or the packages of an install fix are now present.
  signal retry()

  readonly property int pollInterval: 2000
  readonly property int pollLimit: 600000
  readonly property color toneColor: tone === "warn" ? Plugin.Palette.yellow : Color.urgent
  readonly property var packages: Errors.hasInstall(error) ? error.fix.packages : []
  // A new object with the same code (progress resends tool_errors) keeps the install running.
  readonly property string fixKey: error ? String(error.code) : ""
  readonly property string command: compact || !error ? "" : Errors.installCommand(error.fix)
  readonly property string log: error && error.log ? String(error.log) : ""

  function install() {
    Quickshell.execDetached(["omarchy-launch-floating-terminal-with-presentation", "omarchy-pkg-add"].concat(packages))
    waited = 0
    installing = true
  }

  // Views call this when their own Retry runs, so the poll never retries a second time.
  function stopInstalling() {
    installing = false
    waited = 0
  }

  visible: !!error
  implicitHeight: Math.max(Style.space(44), Math.max(body.implicitHeight, actions.implicitHeight) + 2 * Style.space(9))
  color: Util.alpha(toneColor, 0.08)

  onFixKeyChanged: stopInstalling()
  Component.onDestruction: stopInstalling()

  Timer {
    interval: root.pollInterval
    repeat: true
    running: root.installing
    onTriggered: {
      root.waited += interval
      if (root.waited >= root.pollLimit) root.stopInstalling()
      else if (!present.running) present.running = true
    }
  }

  // Exits 0 once every package is installed.
  Process {
    id: present
    command: ["omarchy-pkg-present"].concat(root.packages)
    onExited: (exitCode, exitStatus) => {
      if (!root.installing || exitCode !== 0 || exitStatus !== 0) return
      root.stopInstalling()
      root.retry()
    }
  }

  FontMetrics {
    id: lineMetrics
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }

  Item {
    id: glyph
    anchors.left: parent.left
    anchors.leftMargin: Style.space(16)
    y: body.y
    width: Style.space(14)
    height: lineMetrics.height

    Icon {
      anchors.centerIn: parent
      name: "warn"
      color: root.toneColor
    }
  }

  Column {
    id: body
    anchors.left: glyph.right
    anchors.leftMargin: Style.space(10)
    anchors.right: actions.left
    anchors.rightMargin: actions.width > 0 ? Style.space(10) : 0
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(4)

    Flow {
      width: parent.width
      spacing: Style.space(10)
      visible: titleLabel.text !== "" || root.tokens.length > 0

      Label {
        id: titleLabel
        width: Math.min(implicitWidth, parent.width)
        visible: text !== ""
        text: root.error && root.error.title ? root.error.title : ""
        wrapMode: Text.Wrap
        maximumLineCount: 2
        elide: Text.ElideRight
        color: Color.foreground
        font.pixelSize: Style.font.body
        font.bold: true
      }

      Facts {
        visible: root.tokens.length > 0
        tokens: root.tokens
        fontSize: Style.font.body
      }
    }

    Label {
      width: parent.width
      visible: text !== ""
      text: root.error && root.error.detail ? root.error.detail : ""
      wrapMode: Text.Wrap
      maximumLineCount: root.compact ? 2 : 3
      elide: Text.ElideRight
      font.pixelSize: Style.font.body
    }

    Row {
      visible: root.command !== ""
      spacing: Style.space(8)

      Label {
        anchors.verticalCenter: parent.verticalCenter
        width: Math.min(implicitWidth, body.width - copy.width - parent.spacing)
        elide: Text.ElideRight
        text: root.command
        color: Plugin.Tokens.dim
      }

      ActionButton {
        id: copy
        objectName: root.objectName ? root.objectName + "Copy" : ""
        buttonHeight: Style.space(22)
        fontSize: Style.font.bodySmall
        focusable: root.focusable
        text: "Copy"
        onClicked: Quickshell.execDetached(["wl-copy", root.command])
      }
    }
  }

  Row {
    id: actions
    anchors.right: parent.right
    anchors.rightMargin: Style.space(16)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(8)

    Row {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.installing
      spacing: Style.space(8)

      Spinner {
        anchors.verticalCenter: parent.verticalCenter
        running: root.installing
      }

      Label {
        anchors.verticalCenter: parent.verticalCenter
        text: "Installing in the terminal"
        font.pixelSize: Style.font.body
      }
    }

    ActionButton {
      objectName: root.objectName ? root.objectName + "Install" : ""
      anchors.verticalCenter: parent.verticalCenter
      // Stays pressable while installing: a closed terminal can be opened again.
      visible: root.packages.length > 0
      primary: true
      focusable: root.focusable
      buttonHeight: Style.space(26)
      text: "Install packages"
      onClicked: root.install()
    }

    ActionButton {
      objectName: root.objectName ? root.objectName + "Log" : ""
      anchors.verticalCenter: parent.verticalCenter
      visible: root.log !== ""
      focusable: root.focusable
      buttonHeight: Style.space(26)
      text: "Open log"
      onClicked: Quickshell.execDetached(["omarchy-launch-editor", root.log])
    }

    ActionButton {
      objectName: root.objectName ? root.objectName + "Retry" : ""
      anchors.verticalCenter: parent.verticalCenter
      // An install fix also says "then press Retry", so it gets the button too.
      visible: root.retryHere && root.retryText !== ""
        && (Errors.hasRetry(root.error) || Errors.hasInstall(root.error))
      focusable: root.focusable
      buttonHeight: Style.space(26)
      text: root.retryText
      onClicked: {
        root.stopInstalling()
        root.retry()
      }
    }
  }
}
```

`ui/Banner.qml` (replace the whole file):

```qml
import QtQuick

// `.ban` as an ErrorCard in the yellow tone: a bold lead, optional fact tokens (the disk banner),
// the sentence and a Retry button. An empty action hides the button.
ErrorCard {
  id: root

  property string lead: ""
  property string text: ""
  property string action: "Retry"

  signal triggered()

  tone: "warn"
  retryHere: true
  retryText: action
  error: lead !== "" || text !== ""
    ? ({code: "", title: lead, detail: text, fix: action !== "" ? {kind: "retry"} : null})
    : null
  onRetry: root.triggered()
}
```

- [ ] **Step 7: Show the card on step 1 and grow the panel for it**

```diff
diff --git a/SetupView.qml b/SetupView.qml
index 77fd9cd..db0f97a 100644
--- a/SetupView.qml
+++ b/SetupView.qml
@@ -22,9 +22,11 @@ FocusScope {
   readonly property var size: Setup.panelSize(step)
   readonly property real panelWidth: Style.space(size.width)
   readonly property real panelHeight: Style.space(size.height) + (step === 3 ? indexPage.extraHeight : 0)
+    + (step === 1 ? enginePage.extraHeight : 0)
   readonly property string walkError: service ? Setup.walkError(service.walks) : ""
   readonly property var discover: service ? service.discover : null
-  readonly property string indexFailure: step === 3 && service ? Setup.indexFailure(service.progress, service.setupError) : ""
+  readonly property string indexFailure: step === 3 && service ? Setup.indexFailure(service.progress,
+    service.indexError ? (service.indexError.title + " " + service.indexError.detail).trim() : "") : ""
   readonly property string home: discover && discover.home ? discover.home : (Quickshell.env("HOME") || "")


@@ -64,7 +66,7 @@ FocusScope {

   function ensureScan(force) {
     if (!service || service.scanning) return
-    if (force || !service.discover || service.discoverError !== "" || walkError !== "") service.scan()
+    if (force || !service.discover || !!service.folderError || walkError !== "") service.scan()
   }

   function showFolders() {
@@ -118,7 +120,8 @@ FocusScope {
           stepText: Setup.stepLabel(root.step)
           subtitle: root.step === 1 ? "Everything runs on this machine. Nothing downloads until you press a button."
             : root.step === 3 ? root.indexFailure || "You can search already. Results fill in as files finish."
-            : root.service && !root.service.scanning && root.service.discoverError !== "" ? Setup.folderError(root.service.discoverError)
+            : root.service && !root.service.scanning && root.service.folderError
+              ? (root.service.folderError.title + " " + root.service.folderError.detail).trim()
             : root.walkError !== "" ? Setup.folderError(root.walkError)
             : ""
           subtitleColor: root.step === 2 || root.indexFailure !== "" ? Color.urgent : Plugin.Tokens.dim
diff --git a/ui/SetupEngine.qml b/ui/SetupEngine.qml
index cdb4e6d..33fd3f1 100644
--- a/ui/SetupEngine.qml
+++ b/ui/SetupEngine.qml
@@ -21,6 +21,10 @@ FocusScope {
   readonly property var model: Setup.modelTask(rp)
   readonly property var engine: Setup.engineButton(rp, helperReady)
   readonly property bool ready: Setup.engineReady(rp)
+  readonly property var error: service ? service.engineError : null
+  readonly property string hint: Setup.engineHint(rp)
+  // SetupView grows the panel by this much while the error card shows.
+  readonly property real extraHeight: errorCard.visible ? errorCard.height + column.spacing : 0

   function focusFirst() {
     // With no ready control the scope takes focus, so no ring shows until Tab.
@@ -29,6 +33,16 @@ FocusScope {
     else root.forceActiveFocus()
   }

+  // The footer button and the card's Retry run the same step. Before the helper runs, the card
+  // retries the helper install.
+  function runEngine() {
+    if (!service) return
+    errorCard.stopInstalling()
+    if (!helperReady) service.installHelper()
+    else if (engine.action === "pause") service.runtimePause()
+    else service.runtimeInstall()
+  }
+
   Column {
     id: column
     width: parent.width
@@ -42,7 +56,7 @@ FocusScope {
       tokens: root.helper.tokens
       value: root.helper.value || ""
       valueTone: root.helper.mark === "ok" ? "ok" : "plain"
-      buttonText: root.helper.install ? "Install" : ""
+      buttonText: root.helper.install ? (root.error ? "Retry" : "Install") : ""
       buttonEnabled: !!root.service && !root.service.helperRunning
       onButtonClicked: root.service.installHelper()
     }
@@ -134,6 +148,15 @@ FocusScope {
       }
     }

+    ErrorCard {
+      id: errorCard
+      objectName: "omafindEngineError"
+      width: parent.width
+      error: root.error
+      focusable: true
+      onRetry: root.runEngine()
+    }
+
     Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }

     SetupFacts {
@@ -157,10 +180,13 @@ FocusScope {
       anchors.right: buttons.left
       anchors.rightMargin: Style.space(8)
       anchors.verticalCenter: parent.verticalCenter
+      visible: root.hint !== ""
+      wrapMode: Text.Wrap
+      maximumLineCount: 2
       elide: Text.ElideRight
-      text: Setup.engineHint(root.rp)
+      text: root.hint
       textFormat: Text.PlainText
-      color: root.rp && root.rp.state === "failed" ? Color.urgent : Plugin.Tokens.dim
+      color: Plugin.Tokens.dim
       font.family: Style.font.family
       font.pixelSize: Style.font.bodySmall
     }
@@ -178,11 +204,7 @@ FocusScope {
         enabled: root.engine.enabled
         text: root.engine.text
         focusable: true
-        onClicked: {
-          if (!root.service) return
-          if (root.engine.action === "pause") root.service.runtimePause()
-          else root.service.runtimeInstall()
-        }
+        onClicked: root.runEngine()
       }

       ActionButton {
```

`SetupView.qml` also gets the `folderError`/`indexError` adapters for the header subtitle in the same hunks. Task 7 replaces the subtitle with cards.

- [ ] **Step 8: Keep the other readers working until Task 7**

These are one-expression adapters (title and detail joined as text, or `.title` for a fact token). Task 7 replaces the first four with `ErrorCard`. `PathField` keeps its adapter, because the field shows the failure as one `path` fact.

```diff
--- a/ui/SetupFolders.qml
+++ b/ui/SetupFolders.qml
@@ -198,8 +198,9 @@ FocusScope {

     Label {
-      visible: !!root.service && root.service.setupError !== ""
+      visible: !!root.service && !!root.service.indexError
       width: parent.width
       wrapMode: Text.Wrap
-      text: root.service ? root.service.setupError : ""
+      text: root.service && root.service.indexError
+        ? (root.service.indexError.title + " " + root.service.indexError.detail).trim() : ""
       color: Color.urgent
     }
--- a/ui/SetupIndex.qml
+++ b/ui/SetupIndex.qml
@@ -26,5 +26,5 @@ FocusScope {
   readonly property real extraHeight: showList && problems.length ? list.height + Style.space(8) : 0
   readonly property var bindMap: service ? Keycombo.bindMap(service.binds) : ({})
-  readonly property bool bindsKnown: !!service && (service.bindsReady || service.bindsError !== "")
+  readonly property bool bindsKnown: !!service && (service.bindsReady || !!service.bindsError)
   readonly property var chosenParts: Keycombo.fromHyprland(chosen)
   // The saved chord may be taken by a bind added since; the user must pick another first. A
@@ -213,5 +213,5 @@ FocusScope {
         || (recorder.exposed ? "Hyprland could not enter recording mode. Press Change to try again." : "")
         || root.chosenConflict
-        || (root.service && root.service.bindsError !== "" ? root.service.bindsError + " The shortcut has not been checked for conflicts. Close setup and open it again to retry." : "")
+        || (root.service && root.service.bindsError ? root.service.bindsError.title + " The shortcut has not been checked for conflicts. Close setup and open it again to retry." : "")
       noteTone: note !== "" ? "warn" : ""
       onChange: {
--- a/ui/DriveDialog.qml
+++ b/ui/DriveDialog.qml
@@ -39,5 +39,6 @@ FocusScope {
   readonly property var progress: service ? service.progress : null
   readonly property var footer: Volumes.dialogFooter(progress, uuid, label)
-  readonly property string errorText: service ? service.setupError || service.driveError || (walk ? walk.error : "") : ""
+  readonly property var failure: service ? service.driveError || service.indexError : null
+  readonly property string errorText: failure ? (failure.title + " " + failure.detail).trim() : walk ? walk.error : ""

   readonly property real panelWidth: Style.space(1120)
--- a/ui/PathField.qml
+++ b/ui/PathField.qml
@@ -2,4 +2,5 @@ import QtQuick
 import qs.Commons
 import ".." as Plugin
+import "../lib/errors.js" as Errors

 // The "Add folder" picker inside the overlay (plan D11): a path field completed from `fs_list`.
@@ -28,5 +29,5 @@ Item {
     return listing.dirs.filter(name => name.toLowerCase().indexOf(low) === 0).slice(0, 6)
   }
-  readonly property string error: listing && listing.path === parentPath && listing.error ? listing.error : ""
+  readonly property string error: listing && listing.path === parentPath && listing.error ? Errors.wrap(listing.error).title : ""

   function focusField() {
--- a/SearchView.qml
+++ b/SearchView.qml
@@ -47,13 +47,7 @@ Item {
   // Set while Service.qml brings the daemon to the plugin's build (issue #16).
   readonly property var updateBanner: service && service.update ? Update.banner(service.update) : null
-  readonly property string degradedReason: reply && reply.degraded ? String(reply.degraded)
-    : service && service.warmFailure ? service.warmFailure : ""
-
-  // The daemon sends either a phrase ("indexing in progress", "embedding model unavailable",
-  // "the embedding server did not start") or the bare cause of a server failure.
-  function degradedClause(reason) {
-    if (/^(the embedding server|embedding model|indexing)/.test(reason)) return reason
-    return "the embedding server did not start (" + reason + ")"
-  }
+  // Service.qml turns `degraded` and a failed warm-up into error objects.
+  readonly property var degradedError: reply && reply.degraded ? reply.degraded
+    : service && service.searchError ? service.searchError : null

   signal closeRequested()
@@ -433,14 +427,15 @@ Item {
     anchors.left: parent.left
     anchors.right: parent.right
-    visible: !!root.updateBanner || root.daemonDown || root.degradedReason !== ""
+    visible: !!root.updateBanner || root.daemonDown || !!root.degradedError
       || (!!root.reply && root.reply.t === "error")
     height: visible ? implicitHeight : 0
     action: root.updateBanner ? root.updateBanner.action : "Retry"
     lead: root.updateBanner ? root.updateBanner.lead
-      : root.daemonDown ? "" : root.degradedReason !== "" ? "Semantic search unavailable:" : ""
+      : root.daemonDown ? "" : root.degradedError ? root.degradedError.title
+      : root.reply && root.reply.t === "error" ? root.reply.title || "" : ""
     text: root.updateBanner ? root.updateBanner.text
       : root.daemonDown ? "omafindd is not running. Run systemctl --user start omafind, then retry."
-      : root.degradedReason !== "" ? root.degradedClause(root.degradedReason) + ". Showing keyword matches."
-      : root.reply && root.reply.reason ? String(root.reply.reason) : ""
+      : root.degradedError ? root.degradedError.detail || ""
+      : root.reply && root.reply.t === "error" ? root.reply.detail || String(root.reply.reason || "") : ""
     onTriggered: {
       if (root.updateBanner) {
@@ -451,5 +446,5 @@ Item {
           root.service.connectSocket()
         }
-      } else if (root.degradedReason !== "") {
+      } else if (root.degradedError) {
         root.service.warm()
       } else {
```

- [ ] **Step 9: Run the JS tests**

```bash
node --test "tests/js/*.test.mjs"
```

Expected: all pass (integration run: 246, which includes the 3 retargeted test files).

- [ ] **Step 10: Load and click the card in an offscreen harness**

`qmllint` passing does not prove that a view loads. This step loads the card under `QT_QPA_PLATFORM=offscreen` with stubbed commands, so nothing maps on the desktop and nothing installs.

```bash
work=$(mktemp -d)
mkdir -p "$work/bin" "$work/out"
ln -s /usr/share/omarchy/shell/Commons "$work/Commons"
ln -s "$PWD" "$work/plugin"
for cmd in omarchy-launch-floating-terminal-with-presentation omarchy-launch-editor wl-copy omarchy-pkg-present; do
  printf '#!/bin/sh\necho "%s $*" >> "%s/out/calls.log"\n' "$cmd" "$work" > "$work/bin/$cmd"
  chmod +x "$work/bin/$cmd"
done
cat > "$work/shell.qml" <<'QML'
import QtQuick
import Quickshell
import "plugin/ui" as Parts

FloatingWindow {
  id: window
  implicitWidth: 760
  implicitHeight: 420
  property var retried: []

  function find(item, name) {
    if (item.objectName === name) return item
    for (var i = 0; i < item.children.length; i++) {
      var hit = find(item.children[i], name)
      if (hit) return hit
    }
    return null
  }

  function fact(text) { console.log("fact " + text) }

  Column {
    id: column
    width: 760
    spacing: 8

    Parts.ErrorCard {
      id: red
      objectName: "red"
      width: parent.width
      retryHere: true
      error: ({code: "build-missing-packages", title: "The search engine could not be built.",
        detail: "Missing build packages: vulkan-headers. Install them, then press Retry.",
        fix: {kind: "install", packages: ["vulkan-headers"]}, log: "/tmp/build-runtime.log"})
      onRetry: window.retried.push("red")
    }

    // Retry, a code change and a null error each stop its poll before the first 2 s tick.
    Parts.ErrorCard {
      id: stop
      objectName: "stop"
      width: parent.width
      retryHere: true
      error: ({code: "tool-missing", title: "1 file needs tesseract.",
        detail: "They were indexed without text recognition. Install tesseract and they are indexed again.",
        fix: {kind: "install", packages: ["tesseract"]}})
      onRetry: window.retried.push("stop")
    }

    Parts.ErrorCard {
      objectName: "yellow"
      width: parent.width
      retryHere: true
      error: ({code: "embedding-unavailable", title: "Search by meaning is unavailable.",
        detail: "Vulkan device lost. Showing keyword matches.", fix: {kind: "retry"}})
    }

    Parts.Banner {
      width: parent.width
      lead: "Indexing paused"
      tokens: [{k: "free", v: "1.4 GB"}, {k: "needed", v: "2 GB"}]
      text: "Free some disk space and indexing resumes."
      action: ""
    }

    // Destroyed while installing: its poll must never run.
    Loader {
      id: gone
      width: parent.width
      sourceComponent: Parts.ErrorCard {
        objectName: "gone"
        error: ({code: "tool-missing", title: "1 file needs ffmpeg.", detail: "",
          fix: {kind: "install", packages: ["ffmpeg"]}})
      }
    }
  }

  Timer {
    interval: 500
    running: true
    onTriggered: {
      window.find(red, "redInstall").clicked()
      window.find(red, "redLog").clicked()
      window.find(red, "redCopy").clicked()
      window.find(stop, "stopInstall").clicked()
      window.find(gone.item, "goneInstall").clicked()
    }
  }

  Timer {
    interval: 1000
    running: true
    onTriggered: {
      window.fact("red installing=" + red.installing
        + " install=" + window.find(red, "redInstall").visible
        + " retry=" + window.find(red, "redRetry").visible)
      window.find(red, "redInstall").clicked()
      window.find(stop, "stopRetry").clicked()
      window.fact("stop after-retry installing=" + stop.installing)
      gone.active = false
    }
  }

  Timer {
    interval: 1100
    running: true
    onTriggered: {
      window.find(stop, "stopInstall").clicked()
      stop.error = {code: "tools-missing", title: "Some tools omafind needs are missing.",
        detail: "Missing: fd. Install them, then press Retry.", fix: {kind: "install", packages: ["fd"]}}
      window.fact("stop after-code installing=" + stop.installing)
      window.find(stop, "stopInstall").clicked()
      stop.error = null
      window.fact("stop after-null installing=" + stop.installing)
    }
  }

  Timer {
    interval: 4000
    running: true
    onTriggered: column.grabToImage(result => {
      result.saveToFile(Quickshell.env("OUT") + "/cards.png")
      console.log("retried " + window.retried.join(","))
      Qt.quit()
    })
  }
}
QML
OUT="$work/out" PATH="$work/bin:$PATH" QT_QPA_PLATFORM=offscreen timeout 30 \
  systemd-run --user --scope --quiet --collect -p MemoryMax=2G -p MemorySwapMax=0 -- \
  quickshell -p "$work/shell.qml" > "$work/out/qs.log" 2>&1
grep -iE 'unavailable|Invalid|Cannot read|TypeError|ReferenceError' "$work/out/qs.log"   # expect nothing
grep -E 'fact|retried' "$work/out/qs.log" | sed 's/^.*\(fact\|retried\)/\1/'
sort "$work/out/calls.log"
```

Expected output:

```
fact red installing=true install=true retry=true
fact stop after-retry installing=false
fact stop after-code installing=false
fact stop after-null installing=false
retried stop,red
omarchy-launch-editor /tmp/build-runtime.log
omarchy-launch-floating-terminal-with-presentation omarchy-pkg-add fd
omarchy-launch-floating-terminal-with-presentation omarchy-pkg-add ffmpeg
omarchy-launch-floating-terminal-with-presentation omarchy-pkg-add tesseract
omarchy-launch-floating-terminal-with-presentation omarchy-pkg-add tesseract
omarchy-launch-floating-terminal-with-presentation omarchy-pkg-add vulkan-headers
omarchy-launch-floating-terminal-with-presentation omarchy-pkg-add vulkan-headers
omarchy-pkg-present vulkan-headers
wl-copy sudo pacman -S --needed vulkan-headers
```

What this proves:
- While installing, "Install packages" stays visible and a second press opens the terminal again (two `vulkan-headers` launches), and Retry stays on the card.
- Pressing Retry, a new `error.code` and a null `error` each stop the poll before its first tick, so `omarchy-pkg-present` never runs for `tesseract` or `fd`.
- A card destroyed while installing (`gone`) never polls for `ffmpeg`.
- The `red` poll succeeds once, emits `retry` and stops: exactly one `omarchy-pkg-present vulkan-headers`.

Open `$work/out/cards.png`. Expect a red-wash card with Install packages, Open log, Retry and the pacman line with Copy. Below it the second red card, a yellow card with Retry, then the disk banner with `free 1.4 GB · needed 2 GB` inline after the bold lead. Delete `$work` afterwards.

- [ ] **Step 11: Run the full checks**

```bash
uv run --project helper pytest -q
node --test "tests/js/*.test.mjs"
uv run --project helper ruff check helper tests bin/omafind scripts evals
scripts/qmllint.sh
git diff --check
```

All five must pass. `tests/helper/test_qml_text.py` stays green, because `ErrorCard` uses `Label` only and no caption-size font.

- [ ] **Step 12: Commit**

```bash
git add lib/errors.js ui/ErrorCard.qml ui/Banner.qml Service.qml lib/setup.js ui/SetupEngine.qml SetupView.qml \
  ui/SetupFolders.qml ui/SetupIndex.qml ui/DriveDialog.qml ui/PathField.qml SearchView.qml \
  tests/js/errors.test.mjs tests/js/serviceErrors.test.mjs tests/js/setup.test.mjs \
  tests/js/serviceDiscovery.test.mjs tests/js/shortcutSetup.test.mjs tests/js/discoveryLifecycle.test.mjs
git status --short
git diff --staged --stat
git commit -S -m "fix(setup): show engine errors with their fix and say what install does"
```

---

### Task 7: UI views show every error with one card

Builds on Task 6 as committed. Task 6 already added `Errors.from`, put `update-running` in the warn list, kept `walks[root].error` and `childFolders[path].error` as title strings (one fact token in folder rows), adapted `ui/PathField.qml` to `Errors.wrap(listing.error).title`, and left `ui/FolderTree.qml` unchanged. This task does not touch those again.

> **Decision: the update banner gets two UI codes.** `lib/Update.js` keeps writing its own copy (no daemon reply exists while omafindd restarts), but `Update.banner()` now returns an error object: `update-running` (yellow, no fix) and `update-failed` (red, `fix: {kind: "retry"}`). Task 6's `tone()` already returns `"warn"` for `update-running`. Task 8 lists both codes next to `daemon-offline` and `unknown` as plugin-side codes.

> **Decision: walk errors stay strings, plus one object field.** `Service.receiveCounts` keeps `error` as the title (Task 6) and adds `failure`, the wrapped object, so the drive dialog card keeps the walk's Retry fix. The Folders step does not need it: Task 6 already copies a failed walk's object into `folderError`.

**Files:**
- Modify: `lib/results.js` (import, append `bannerFor`), `lib/Update.js` (`banner`), `lib/volumes.js` (`paused`, `diskBanner`)
- Modify: `lib/setup.js` (`indexHead` exit token; remove `indexFailure` and the header sentence `folderError`; add `problemTokens`)
- Modify: `Service.qml` (`receiveCounts`: walk entries gain `failure`)
- Modify: `SearchView.qml` (banner slot `ErrorCard`, `retryBanner`, `previewFailed`, start log `FileView`, disk banner from the `disk-low` object, `openStarted` carries the request)
- Modify: `Overlay.qml` (open failure toast with Retry), `ui/Toast.qml` (`showError`, `dismiss`, sticky toast with "Dismiss"), `ui/PreviewLayer.qml` (compact card in the media area)
- Modify: `SetupView.qml`, `ui/SetupHeader.qml` (no error text in the header), `ui/SetupFolders.qml` (folder card), `ui/SetupIndex.qml` (index, tool-missing, binds and save cards; problem rows), `ui/DriveDialog.qml` (drive card)
- Modify: `tests/fixtures/results/degraded.json`, `tests/fixtures/setup/progress.json`
- Create: `tests/js/overlay.test.mjs`
- Test: `tests/js/searchView.test.mjs`, `results.test.mjs`, `update.test.mjs`, `volumes.test.mjs`, `setup.test.mjs`, `driveDialog.test.mjs`, `previewPane.test.mjs`; Task 6's retargeted `serviceDiscovery.test.mjs` (walk `failure`) and `shortcutSetup.test.mjs` (the binds sentence leaves the shortcut note).

**Interfaces:**

Consumes:
- Task 6 `lib/errors.js`: `wrap`, `from`, `tone`, `offline(logPath)`, `hasRetry`, `hasInstall`.
- Task 6 `ui/ErrorCard.qml`: `error`, `retryHere`, `compact`, `focusable`, signal `retry()`, child objectNames `<name>Install`, `<name>Log`, `<name>Retry`, `<name>Copy`; hidden while `error` is null. With `retryHere`, Retry shows for a retry fix and for an install fix.
- Task 6 `ui/Banner.qml`: `lead`, `tokens`, `text`, `action` (the disk banner keeps this fact-token form).
- Task 6 `Service.qml`, each an object or null: `folderError` (also gets a failed walk's object and the setup half of a failed `shell.json` save), `driveError` (the drive half), `indexError` (cleared by `startIndexing`), `bindsError`, `searchError` (cleared by `warm()`); `retryFailed(code)`; `itemFailed(message)` for every `t:"error"` that carries `id`.
- Task 2: `results.degraded`, `open_failed.error`, `paused.error` are objects; `t:"error"` replies carry the object's fields at top level.
- Task 3: `<data>/cache/logs/omafindd-start.log`, present only while the last start failed.
- Task 5: `progress.problems` items are `{path, code, detail}`; `progress.tool_errors` is a list of `tool-missing` objects.

Produces:
- `Results.bannerFor({update, offline, reply, warm})` → `{error, retry}` or null; `retry` is `"update"`, `"connect"`, `"warm"` or `"search"`.
- `Update.banner(state)` → `update-running` or `update-failed` object, or null.
- `Volumes.diskBanner(state)` → `{error, tokens}`; `state.disk.error` holds the `disk-low` object.
- `Setup.problemTokens(problem, home)`; `Setup.indexHead(...).side` gains `exit N` after a failed run. `Setup.indexFailure` and `Setup.folderError` are removed.
- `Service.walks[root].failure` (object or null) next to the title string `error`.
- `SearchView.openStarted(item, how, message)` (third argument added); `SearchView.retryBanner()`, `SearchView.previewFailed(message)`.
- `Toast.showError(error)`, `Toast.dismiss()`, `Toast.failure`, `Toast.sticky`, signal `Toast.retryRequested()`.
- `Overlay.failOpen(error)`, `Overlay.retryOpen()`, `Overlay.failedOpen`.
- `SetupFolders.failure` (`folderError`, else `indexError`) and `SetupFolders.retry()`; `DriveDialog.driveFailure()` and `DriveDialog.retry()`; `SetupIndex.retryIndex()`.
- objectNames: `omafindSearchError`, `omafindDiskBanner`, `omafindPreviewError`, `omafindToastError`, `omafindToastDismiss`, `omafindFolderError`, `omafindIndexError`, `omafindToolError`, `omafindBindsError`, `omafindSaveError`, `omafindDriveError`.

- [ ] **Step 1: Write the failing tests**

Create `tests/js/overlay.test.mjs`:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { load } from './load.mjs';
import { plain } from './fixtures.mjs';

const timer = () => ({ running: false, restart() { this.running = true; }, stop() { this.running = false; } });

function overlay(values = {}) {
  const shown = [];
  const ctx = vm.createContext({ Errors: load('errors.js'), pendingOpen: null, failedOpen: null,
    opened: false, service: null, searchView: { flash: 'acc' }, closeTimer: timer(), openTimeout: timer(),
    toast: { dismissed: 0, showError(error) { shown.push(error); }, dismiss() { this.dismissed++; } },
    ...values });
  ctx.root = ctx;
  const source = readFileSync(new URL('../../Overlay.qml', import.meta.url), 'utf8');
  for (const match of source.matchAll(/^  function \w+\([^]*?^  \}/gm)) vm.runInContext(match[0], ctx);
  return { ctx, shown };
}

const item = { id: 'pdf:1', name: 'a.pdf' };
const message = { t: 'open', id: 'pdf:1', how: 'open', line: 12 };
const notConnected = { code: 'drive-not-mounted', title: 'Photos2024 is not connected.',
  detail: 'Connect it, then press Retry.', fix: { kind: 'retry' } };

test('error replies give the toast only the error fields', () => {
  const { Errors } = overlay().ctx;
  assert.deepEqual(plain(Errors.from({ t: 'error', id: 'pdf:1', for: 'open', code: 'open-failed',
    title: 'a.pdf could not be opened.', detail: 'Permission denied.', fix: { kind: 'retry' } })),
  { code: 'open-failed', title: 'a.pdf could not be opened.', detail: 'Permission denied.', fix: { kind: 'retry' } });
  assert.deepEqual(plain(Errors.from({ t: 'open_failed', id: 'pdf:1', error: notConnected })), notConnected);
  assert.deepEqual(plain(Errors.from({ t: 'open_failed', id: 'pdf:1', reason: 'missing' })),
    { code: 'unknown', title: 'missing', detail: '' });
  assert.equal(Errors.from({ t: 'discover_counts', root: '/h' }), null);
});

test('a failed open shows the error and keeps the request for Retry', () => {
  const { ctx, shown } = overlay({
    pendingOpen: { id: 'pdf:1', how: 'open', item, message, reply: null, closed: false } });
  ctx.closeTimer.running = true;
  ctx.openTimeout.running = true;
  ctx.failOpen(notConnected);
  assert.equal(ctx.pendingOpen, null);
  assert.equal(ctx.searchView.flash, '');
  assert.equal(ctx.closeTimer.running, false);
  assert.equal(ctx.openTimeout.running, false);
  assert.deepEqual(plain(shown), [notConnected]);
  assert.deepEqual(plain(ctx.failedOpen), { message, item, how: 'open' });
});

test('Retry sends the same open again and announces it as a first open', () => {
  const sent = [];
  const { ctx } = overlay({ service: { send(m) { sent.push(m); return true; } },
    failedOpen: { message, item, how: 'open' } });
  ctx.retryOpen();
  assert.deepEqual(plain(sent), [message]);
  assert.equal(ctx.toast.dismissed, 1);
  assert.equal(ctx.failedOpen, null);
  assert.deepEqual(plain(ctx.pendingOpen),
    { id: 'pdf:1', how: 'open', item, message, reply: null, closed: true });
  assert.equal(ctx.openTimeout.running, true);
  assert.equal(ctx.closeTimer.running, false);
});

test('Retry with the overlay open closes it as a first open does', () => {
  const { ctx } = overlay({ opened: true, service: { send() { return true; } },
    failedOpen: { message, item, how: 'open' } });
  ctx.retryOpen();
  assert.equal(ctx.pendingOpen.closed, false);
  assert.equal(ctx.closeTimer.running, true);
});

test('Retry does nothing when the request cannot be sent', () => {
  const { ctx } = overlay({ service: { send() { return false; } }, failedOpen: { message, item, how: 'open' } });
  ctx.retryOpen();
  assert.equal(ctx.pendingOpen, null);
  assert.equal(ctx.toast.dismissed, 1);
});
```

`tests/js/searchView.test.mjs`: banner Retry by source, and preview errors.

```diff
diff --git a/tests/js/searchView.test.mjs b/tests/js/searchView.test.mjs
index 5e3b16f..232866a 100644
--- a/tests/js/searchView.test.mjs
+++ b/tests/js/searchView.test.mjs
@@ -3,6 +3,7 @@ import assert from 'node:assert/strict';
 import { readFileSync } from 'node:fs';
 import vm from 'node:vm';
 import { load } from './load.mjs';
+import { plain } from './fixtures.mjs';

 function view(values = {}) {
   const context = vm.createContext({
@@ -87,3 +88,39 @@ test('an early timer tick re-arms the timer for the remaining time', () => {
   context.due('meaning-due');
   assert.deepEqual(armed, [50]);
 });
+
+test('banner Retry follows the source of the card', () => {
+  const calls = [];
+  const service = { retryUpdate: () => calls.push('update'), checkUnit: () => calls.push('unit'),
+    connectSocket: () => calls.push('connect'), warm: () => calls.push('warm') };
+  for (const [retry, expected] of [['update', ['update']], ['connect', ['unit', 'connect']], ['warm', ['warm']]]) {
+    calls.length = 0;
+    view({ service, bannerView: { error: {}, retry } }).retryBanner();
+    assert.deepEqual(calls, expected);
+  }
+});
+
+test('banner Retry on a search error sends the query again', () => {
+  const armed = [];
+  const context = view({ service: {}, bannerView: { error: {}, retry: 'search' },
+    SearchState: load('format.js', 'results.js', 'searchState.js'),
+    Date: { now: () => 5000 },
+    meaningTimer: { interval: 0, restart() { armed.push(this.interval); } },
+    search: { query: 'router', seq: 3, phase: 'done', sentWords: 3, sentMeaning: 3, reply: null, started: 0 } });
+  context.retryBanner();
+  assert.equal(context.search.seq, 4);
+  assert.equal(context.search.phase, 'words');
+  assert.deepEqual(armed, [200]);
+});
+
+test('a preview error replaces the preview of the selected row', () => {
+  const context = view({ Errors: load('errors.js'), selectedItem: { id: 'pdf:1' }, preview: null });
+  const reply = { t: 'error', id: 'pdf:1', code: 'file-missing', title: 'a.pdf is missing.',
+    detail: 'It was moved or deleted after it was indexed.' };
+  context.previewFailed({ ...reply, id: 'pdf:2' });
+  context.previewFailed({ ...reply, for: 'open' });
+  assert.equal(context.preview, null);
+  context.previewFailed(reply);
+  assert.deepEqual(plain(context.preview), { id: 'pdf:1', error: { code: 'file-missing',
+    title: 'a.pdf is missing.', detail: 'It was moved or deleted after it was indexed.' } });
+});
```

`tests/js/results.test.mjs`:

```diff
diff --git a/tests/js/results.test.mjs b/tests/js/results.test.mjs
index 546e53d..a84b96f 100644
--- a/tests/js/results.test.mjs
+++ b/tests/js/results.test.mjs
@@ -105,6 +105,9 @@ test('footer copy uses daemon totals, weaker counts, phases, and code prefix', (
   assert.equal(footerLeft({ reply: { total: 4, weaker: 5 }, prefix: 'code:' }), '4 results in your code · 5 weaker');
   assert.equal(footerLeft({ reply: { total: 1, weaker: 0 } }), '1 result');
   assert.equal(footerLeft({ reply: { total: 1204, weaker: 0 } }), '1,204 results');
+  assert.equal(footerLeft({ reply: { total: 2, weaker: 0, degraded: { code: 'server-starting',
+    title: 'The embedding server is starting.', detail: 'Showing keyword matches until it is ready.' } },
+  phase: 'degraded' }), '2 results · keyword matches only');
 });

 test('idle footer uses offline labels and only shows incomplete indexing progress', () => {
@@ -146,3 +149,24 @@ test('a code search before the first code index says the index is pending', () =
     reply: { total: 0, items: [], notice: 'code-index-pending' } }),
     'The code index is not built yet. It is built on the next index run.');
 });
+
+test('the banner slot shows one error and names what its Retry does', () => {
+  const R = load('format.js', 'errors.js', 'results.js');
+  const update = { code: 'update-failed', title: 'omafindd did not update.',
+    detail: 'uv sync failed. Press Retry to try again.', fix: { kind: 'retry' } };
+  const offline = R.offline('');
+  const degraded = fixture('degraded');
+  const warm = { code: 'server-start-failed', title: 'The embedding server did not start.',
+    detail: 'It exited with code 1. Showing keyword matches until it starts.', fix: { kind: 'retry' } };
+  assert.equal(R.bannerFor({ reply: fixture('main') }), null);
+  assert.deepEqual(plain(R.bannerFor({ update, offline, reply: degraded })), { error: update, retry: 'update' });
+  assert.equal(R.bannerFor({ offline, reply: degraded }).retry, 'connect');
+  assert.deepEqual(plain(R.bannerFor({ reply: degraded, warm })), { error: plain(degraded.degraded), retry: 'warm' });
+  assert.deepEqual(plain(R.bannerFor({ reply: fixture('main'), warm })), { error: warm, retry: 'warm' });
+  assert.deepEqual(plain(R.bannerFor({ reply: { t: 'error', seq: 4, code: 'no-index',
+    title: 'Nothing is indexed yet.', detail: 'Open setup and start the first index.' } })),
+  { error: { code: 'no-index', title: 'Nothing is indexed yet.', detail: 'Open setup and start the first index.' },
+    retry: 'search' });
+  assert.deepEqual(plain(R.bannerFor({ reply: { ...fixture('main'), degraded: 'Vulkan device lost' } })),
+    { error: { code: 'unknown', title: 'Vulkan device lost', detail: '' }, retry: 'search' });
+});
```

`tests/js/update.test.mjs`:

```diff
diff --git a/tests/js/update.test.mjs b/tests/js/update.test.mjs
index 5fe2ae8..cc8a781 100644
--- a/tests/js/update.test.mjs
+++ b/tests/js/update.test.mjs
@@ -119,12 +119,18 @@ test('a ready or unknown venv, or no local build, runs nothing', () => {
   assert.deepEqual(run([{ type: 'venv', state: 'stale' }]).effects, []);
 });

-test('the banner names the update phase', () => {
+test('the banner is an error object for each update phase', () => {
   const { banner } = load('Update.js');
   assert.equal(banner(initial()), null);
-  assert.deepEqual(plain(banner({ ...initial(), phase: 'updating' })), { lead: '', action: '',
-    text: 'Updating omafindd to match the installed plugin. Search returns when it restarts.' });
+  assert.deepEqual(plain(banner({ ...initial(), phase: 'updating' })), { code: 'update-running',
+    title: 'omafindd is updating to match the installed plugin.', detail: 'Search returns when it restarts.' });
   assert.deepEqual(plain(banner({ ...initial(), phase: 'failed', error: 'uv sync failed.' })), {
-    lead: 'omafindd did not update:', action: 'Retry',
-    text: 'uv sync failed. Press Retry to run bin/omafind setup again.' });
+    code: 'update-failed', title: 'omafindd did not update.',
+    detail: 'uv sync failed. Press Retry to try again.', fix: { kind: 'retry' } });
+});
+
+test('a running update is a yellow card and a failed one is red', () => {
+  const { tone } = load('errors.js');
+  assert.equal(tone('update-running'), 'warn');
+  assert.equal(tone('update-failed'), 'urgent');
 });
```

`tests/js/volumes.test.mjs`:

```diff
diff --git a/tests/js/volumes.test.mjs b/tests/js/volumes.test.mjs
index c27ec14..d24a699 100644
--- a/tests/js/volumes.test.mjs
+++ b/tests/js/volumes.test.mjs
@@ -148,13 +148,14 @@ test('settings replace ignored UUIDs and suppress pending prompts for those driv

 test('paused shows the disk banner and resumed clears it', () => {
   const v = volumes();
+  const diskLow = {code: 'disk-low', title: 'Indexing is paused.',
+    detail: 'Free some disk space and indexing resumes by itself.'};
   assert.equal(v.diskBanner(v.initial()), null);
   const result = v.reduce(freeze(v.initial()), {type: 'paused',
-    message: freeze({t: 'paused', reason: 'disk', free_gb: 1.4, need_gb: 2})});
-  assert.deepEqual(plain(result.state.disk), {free_gb: 1.4, need_gb: 2});
-  assert.deepEqual(plain(v.diskBanner(result.state)), {title: 'Indexing paused',
-    tokens: [{k: 'free', v: '1.4 GB'}, {k: 'needed', v: '2 GB'}],
-    text: 'Free some disk space and indexing resumes.'});
+    message: freeze({t: 'paused', error: diskLow, free_gb: 1.4, need_gb: 2})});
+  assert.deepEqual(plain(result.state.disk), {free_gb: 1.4, need_gb: 2, error: diskLow});
+  assert.deepEqual(plain(v.diskBanner(result.state)), {error: diskLow,
+    tokens: [{k: 'free', v: '1.4 GB'}, {k: 'needed', v: '2 GB'}]});
   const resumed = v.reduce(freeze(result.state), {type: 'resumed'});
   assert.equal(resumed.state.disk, null);
   assert.equal(v.diskBanner(resumed.state), null);
```

`tests/js/setup.test.mjs`: the exit token replaces `indexFailure`, the header sentence `folderError` goes, problem rows carry code and detail. The walk error tests stay as Task 6 left them (title strings).

```diff
diff --git a/tests/js/setup.test.mjs b/tests/js/setup.test.mjs
index f8c7ede..c62c763 100644
--- a/tests/js/setup.test.mjs
+++ b/tests/js/setup.test.mjs
@@ -98,11 +98,12 @@ test('estimates and problem facts tolerate data that has not arrived', () => {
   assert.deepEqual(plain(s.problemFacts(null)), []);
 });

-test('index failure prefers the daemon sentence, then a failed exit code',()=>{
-  assert.equal(s.indexFailure({running:false,exit:2},'Indexing stopped. See ~/.local/state/omafind/index.log.'),'Indexing stopped. See ~/.local/state/omafind/index.log.');
-  assert.equal(s.indexFailure({running:false,exit:2},''),'exit 2');
-  assert.equal(s.indexFailure({running:false,exit:0},''),'');
-  assert.equal(s.indexFailure({running:true},''),'');assert.equal(s.indexFailure(null,''),'');
+test('a failed run adds an exit token to the index header', () => {
+  const stopped = {...progress, running: false, device: null, vram_gb: null};
+  assert.deepEqual(values(s.indexHead({...stopped, exit: 2}, discover.rates).side), [['exit', '2']]);
+  assert.deepEqual(values(s.indexHead({...stopped, exit: 0}, discover.rates).side), []);
+  assert.deepEqual(values(s.indexHead({...stopped, exit: 2, running: true}, discover.rates).side), []);
+  assert.equal(s.indexFailure, undefined);
 });

 test('step 3 title follows the run outcome', () => {
@@ -110,7 +111,7 @@ test('step 3 title follows the run outcome', () => {
   assert.equal(s.indexTitle({...progress, running: true}, ''), 'Indexing your files');
   assert.equal(s.indexTitle({...progress, running: false, done: 5, queued: 0}, ''), 'Indexing finished');
   assert.equal(s.indexTitle({...progress, running: false, exit: 1}, 'exit 1'), 'Indexing stopped');
-  assert.equal(s.indexTitle({...progress, running: true}, 'No folders are selected.'), 'Indexing stopped');
+  assert.equal(s.indexTitle({...progress, running: true}, {code: 'no-roots', title: 'No folders are selected.', detail: 'Pick at least one folder to index.'}), 'Indexing stopped');
 });


@@ -149,11 +150,15 @@ test('failed walks show no scan time', () => {
     [['folders', '12']]);
 });

-test('folder errors trim tool prefixes and trailing punctuation and give a next step', () => {
-  assert.equal(s.folderError('fd failed: Permission denied.\n'),
-    'Could not list your folders: Permission denied. Press Back and try again.');
-  assert.equal(s.folderError('Connection lost!'),
-    'Could not list your folders: Connection lost. Press Back and try again.');
+test('the header no longer builds folder error sentences', () => {
+  assert.equal(s.folderError, undefined);
+});
+
+test('problem rows show the code, the detail and the path', () => {
+  assert.deepEqual(values(s.problemTokens(progress.problems[0], '/home/u')),
+    [['encrypted-pdf', 'pdfinfo failed: Incorrect password'], ['path', '~/Documents/a.pdf']]);
+  assert.deepEqual(values(s.problemTokens({path: '/home/u/b.pdf', reason: 'timeout'}, '/home/u')),
+    [['timeout', ''], ['path', '~/b.pdf']]);
 });

 const idle = freeze({ ...plain(runtime), state: 'idle', step: null, file: null, done: 0, left_seconds: null,
```

`tests/js/driveDialog.test.mjs`:

```diff
diff --git a/tests/js/driveDialog.test.mjs b/tests/js/driveDialog.test.mjs
index 1e7ed54..4eb9269 100644
--- a/tests/js/driveDialog.test.mjs
+++ b/tests/js/driveDialog.test.mjs
@@ -34,3 +34,32 @@ test('drive save carries excludes and code choices and preserves other volumes',
     { path: '/m/Photos', volume: 'usb', excludes: ['data'] }], ['/h/code', '/m/repo'], 'usb']);
   assert.equal(ctx.phase, 'run');
 });
+
+test('the dialog shows its own error, then the walk, then the drive index run', () => {
+  const own = { code: 'drive-not-mounted', title: 'Photos2024 is not connected.',
+    detail: 'Connect it, then press Retry.', fix: { kind: 'retry' } };
+  const walk = { code: 'scan-failed', title: '/m could not be scanned.',
+    detail: 'Permission denied. Press Retry to scan it again.', fix: { kind: 'retry' } };
+  const index = { code: 'index-exited', title: 'Indexing stopped.',
+    detail: 'The indexer exited with code 2. Open the log for the cause, then press Retry.', fix: { kind: 'retry' } };
+  const ctx = dialog({ service: { driveError: own, indexError: index },
+    walk: { done: true, error: walk.title, failure: walk } });
+  assert.equal(ctx.driveFailure(), own);
+  ctx.service.driveError = null;
+  assert.equal(ctx.driveFailure(), walk);
+  ctx.walk = { done: true, error: '', failure: null };
+  assert.equal(ctx.driveFailure(), null);
+  ctx.phase = 'run';
+  assert.equal(ctx.driveFailure(), index);
+});
+
+test('Retry scans the drive again while picking and indexes it again after', () => {
+  const calls = [];
+  const ctx = dialog({ service: { scanDrive: uuid => calls.push(['scan', uuid]),
+    settings: { roots: [], codeRoots: [] },
+    startIndexing: (roots, code, volume) => { calls.push(['index', volume]); return true; } } });
+  ctx.retry();
+  ctx.phase = 'run';
+  ctx.retry();
+  assert.deepEqual(calls, [['scan', 'usb'], ['index', 'usb']]);
+});
```

`tests/js/previewPane.test.mjs` (it passes before the change too; it pins that an error preview reaches its layer unchanged):

```diff
diff --git a/tests/js/previewPane.test.mjs b/tests/js/previewPane.test.mjs
index 2083297..194cb29 100644
--- a/tests/js/previewPane.test.mjs
+++ b/tests/js/previewPane.test.mjs
@@ -58,3 +58,18 @@ test('a readiness notification and timeout cannot swap twice', () => {
   ctx.swap();
   assert.equal(ctx.current.item.id, 'b');
 });
+
+test('a preview error reaches the layer that shows its item', () => {
+  const ctx = pane();
+  const source = readFileSync(new URL('../../ui/PreviewPane.qml', import.meta.url), 'utf8');
+  vm.runInContext('function previewChanged() {' + source.match(/^  onPreviewChanged: \{([^]*?)^  \}/m)[1] + '}', ctx);
+  const error = { code: 'file-missing', title: 'a.pdf is missing.', detail: 'It was moved or deleted after it was indexed.' };
+  ctx.first.item = { id: 'a' }; ctx.first.shown = true; ctx.pendingSwap = false;
+  ctx.preview = { id: 'a', error };
+  ctx.previewChanged();
+  assert.equal(ctx.first.preview.error, error);
+  ctx.show({ id: 'b' });
+  ctx.preview = { id: 'b', error };
+  ctx.previewChanged();
+  assert.equal(ctx.second.preview.error, error);
+});
```

`tests/js/serviceDiscovery.test.mjs` and `tests/js/shortcutSetup.test.mjs` (Task 6 files):

```diff
diff --git a/tests/js/serviceDiscovery.test.mjs b/tests/js/serviceDiscovery.test.mjs
index 21a93a2..c838831 100644
--- a/tests/js/serviceDiscovery.test.mjs
+++ b/tests/js/serviceDiscovery.test.mjs
@@ -26,7 +26,8 @@ test('counts merge batches and retain errors and dataset evidence', () => {
   ctx.receiveCounts({ root: '/h', counts: { '/h/b': { pdf: 1 } }, done: true,
     seconds: 0.4, error: 'fd failed', datasets: [{ path: '/h/a/data', kind: 'image' }] });
   assert.deepEqual(plain(ctx.discoverCounts), { '/h/a': { text: 2 }, '/h/b': { pdf: 1 } });
-  assert.deepEqual(plain(ctx.walks['/h']), { done: true, seconds: 0.4, error: 'fd failed' });
+  assert.deepEqual(plain(ctx.walks['/h']), { done: true, seconds: 0.4, error: 'fd failed',
+    failure: { code: 'unknown', title: 'fd failed', detail: '' } });
   assert.equal(ctx.datasets['/h/a/data'].kind, 'image');
 });

```

```diff
diff --git a/tests/js/shortcutSetup.test.mjs b/tests/js/shortcutSetup.test.mjs
index c670515..f8d0706 100644
--- a/tests/js/shortcutSetup.test.mjs
+++ b/tests/js/shortcutSetup.test.mjs
@@ -106,7 +106,8 @@ test('saving allows unknown binds after an error but waits for cleanup', () => {
   assert.equal(saveEnabled(), false);
   ctx.service.bindsError = { code: 'binds-failed', title: 'Your Hyprland bindings could not be read.', detail: '' };
   assert.equal(saveEnabled(), true);
-  assert.match(rowValue('note'), /not been checked for conflicts/);
+  // The binds card shows the failure, so the shortcut note stays empty.
+  assert.equal(rowValue('note'), '');
   ctx.recorder.operation = 'leave';
   assert.equal(saveEnabled(), false);
   ctx.recorder.operation = '';
```

Fixtures:

```diff
diff --git a/tests/fixtures/results/degraded.json b/tests/fixtures/results/degraded.json
index 37682bf..848d385 100644
--- a/tests/fixtures/results/degraded.json
+++ b/tests/fixtures/results/degraded.json
@@ -12,7 +12,13 @@
   },
   "total": 6,
   "weaker": 0,
-  "degraded": "Vulkan device lost",
+  "degraded": {
+    "code": "embedding-unavailable",
+    "title": "Search by meaning is unavailable.",
+    "detail": "Vulkan device lost. Showing keyword matches.",
+    "fix": {"kind": "retry"},
+    "log": "/home/u/.local/share/omafind/cache/logs/llama-server.log"
+  },
   "items": [
     {
       "id": "image:1",
```

```diff
diff --git a/tests/fixtures/setup/progress.json b/tests/fixtures/setup/progress.json
index 12392f1..141f434 100644
--- a/tests/fixtures/setup/progress.json
+++ b/tests/fixtures/setup/progress.json
@@ -40,7 +40,8 @@
   "problems": [
     {
       "path": "/home/u/Documents/a.pdf",
-      "reason": "encrypted-pdf"
+      "code": "encrypted-pdf",
+      "detail": "pdfinfo failed: Incorrect password"
     }
   ]
 }
```

- [ ] **Step 2: Run them to see them fail**

```bash
node --test "tests/js/*.test.mjs"
```

Expected failures:
- `overlay.test.mjs`: `failOpen` calls `toast.show`, which the stub lacks; `retryOpen is not defined`.
- `searchView.test.mjs`: `retryBanner is not defined`, `previewFailed is not defined`.
- `results.test.mjs`: `R.bannerFor is not a function`. The new footer line passes already.
- `update.test.mjs`: the banner still returns `{lead, action, text}`.
- `volumes.test.mjs`: `state.disk` lacks `error`; `diskBanner` returns `{title, tokens, text}`.
- `setup.test.mjs`: `side` lacks `exit`; `indexFailure` and `folderError` are still defined; `problemTokens` is not a function.
- `driveDialog.test.mjs`: `driveFailure is not defined`, `retry is not defined`.
- `serviceDiscovery.test.mjs`: the walk has no `failure`. `shortcutSetup.test.mjs`: the note still carries the binds sentence.
- `previewPane.test.mjs`: passes (pass-through pin).

- [ ] **Step 3: Implement `lib/results.js`, `lib/Update.js`, `lib/volumes.js`**

```diff
diff --git a/lib/results.js b/lib/results.js
index 808556a..2f3be9d 100644
--- a/lib/results.js
+++ b/lib/results.js
@@ -1,8 +1,10 @@
 .pragma library
 .import "format.js" as Format
+.import "errors.js" as Errors

 // QML supplies import namespaces; the Node loader shares one global context.
 var F = typeof Format !== "undefined" ? Format : this
+var E = typeof Errors !== "undefined" ? Errors : this

 function sectionTitle(kind) {
   return {image: "Images", video: "Video", audio: "Audio", pdf: "PDFs", text: "Documents", code: "Code"}[kind]
@@ -130,3 +132,18 @@ function footerIdle(status) {
       fraction: status.done / status.total} : null
   return {text: text, progress: progress}
 }
+
+// Codes whose Retry restarts the embedding server instead of searching again.
+var WARM_CODES = ["server-start-failed", "embedding-unavailable", "server-starting"]
+
+// The search banner slot shows one error. `retry` names what the card's Retry does.
+function bannerFor(view) {
+  if (view.update) return {error: view.update, retry: "update"}
+  if (view.offline) return {error: view.offline, retry: "connect"}
+  var reply = view.reply || {}
+  var error = reply.degraded != null ? E.wrap(reply.degraded)
+    : view.warm ? E.wrap(view.warm)
+    : reply.t === "error" ? E.from(reply) : null
+  if (!error) return null
+  return {error: error, retry: WARM_CODES.indexOf(error.code) >= 0 ? "warm" : "search"}
+}
```

`footerLeft` needs no change: `reply.degraded != null` holds for an object.

```diff
diff --git a/lib/Update.js b/lib/Update.js
index 8c5cf83..1c72ce0 100644
--- a/lib/Update.js
+++ b/lib/Update.js
@@ -49,13 +49,14 @@ function reduce(state, event) {
   return {state: next, effects: effects}
 }

-// The search banner for an update, or null when there is none.
+// The search banner for an update as an error object, or null. No daemon is there to write the
+// copy while omafindd restarts, so the codes are the plugin's own.
 function banner(state) {
   if (state.phase === "updating")
-    return {lead: "", action: "",
-      text: "Updating omafindd to match the installed plugin. Search returns when it restarts."}
+    return {code: "update-running", title: "omafindd is updating to match the installed plugin.",
+      detail: "Search returns when it restarts."}
   if (state.phase === "failed")
-    return {lead: "omafindd did not update:", action: "Retry",
-      text: state.error.replace(/\.$/, "") + ". Press Retry to run bin/omafind setup again."}
+    return {code: "update-failed", title: "omafindd did not update.",
+      detail: state.error.replace(/\.$/, "") + ". Press Retry to try again.", fix: {kind: "retry"}}
   return null
 }
```

```diff
diff --git a/lib/volumes.js b/lib/volumes.js
index 8d3d36a..2149271 100644
--- a/lib/volumes.js
+++ b/lib/volumes.js
@@ -43,7 +43,7 @@ function reduce(state, event) {
       label: message.label || (previous && previous.label) || driveLabel(next.drives[message.uuid] || {uuid: message.uuid}),
       done: message.done, total: message.total, done_at: doneAt}
   } else if (event.type === "paused") {
-    next.disk = {free_gb: message.free_gb, need_gb: message.need_gb}
+    next.disk = {free_gb: message.free_gb, need_gb: message.need_gb, error: message.error || null}
   } else if (event.type === "resumed") {
     next.disk = null
   } else if (event.type === "decide") {
@@ -91,11 +91,11 @@ function footer(state, now) {
     fraction: rec.done_at !== null ? 1 : rec.total ? rec.done / rec.total : 0}
 }

+// The daemon's disk-low error, with the free and needed space as fact tokens.
 function diskBanner(state) {
   if (!state.disk) return null
-  return {title: "Indexing paused",
-    tokens: [{k: "free", v: state.disk.free_gb + " GB"}, {k: "needed", v: state.disk.need_gb + " GB"}],
-    text: "Free some disk space and indexing resumes."}
+  return {error: state.disk.error,
+    tokens: [{k: "free", v: state.disk.free_gb + " GB"}, {k: "needed", v: state.disk.need_gb + " GB"}]}
 }

 function indexedToken(files) {
```

- [ ] **Step 4: Implement `lib/setup.js`**

```diff
diff --git a/lib/setup.js b/lib/setup.js
index b140f11..a9e28b2 100644
--- a/lib/setup.js
+++ b/lib/setup.js
@@ -192,17 +192,10 @@ function indexHead(progress, rates) {
   }
   if (p.device) side.push(token("device", p.device.toUpperCase()))
   if (p.vram_gb != null) side.push(token("vram", p.vram_gb + " GB"))
+  if (!p.running && p.exit != null && p.exit !== 0) side.push(token("exit", p.exit, "warn"))
   return {count: count(p.done), facts: facts, side: side, spinning: !!p.running, fraction: fraction(p.done, total)}
 }

-// Step 3 failure line: the daemon's error sentence, else `exit N` from a finished run that failed.
-// "" while the run is fine.
-function indexFailure(progress, error) {
-  if (error) return error
-  if (progress && !progress.running && progress.exit != null && progress.exit !== 0) return "exit " + progress.exit
-  return ""
-}
-
 function indexTitle(progress, failure) {
   if (failure || (progress && !progress.running && (progress.queued > 0 || progress.exit))) return "Indexing stopped"
   if (progress && !progress.running && progress.done > 0 && !progress.queued) return "Indexing finished"
@@ -236,9 +229,10 @@ function walkError(walks) {
   return ""
 }

-function folderError(error) {
-  var reason = String(error).trim().replace(/^fd failed:\s*/, "").replace(/[.!?;:]+$/, "")
-  return "Could not list your folders: " + reason + ". Press Back and try again."
+// A per-file problem row: its code with the extractor's detail, then the path.
+function problemTokens(problem, home) {
+  return [token(problem.code || problem.reason || "failed", problem.detail || ""),
+    token("path", displayPath(problem.path, home))]
 }

 function datasetFacts(evidence) {
```

The `index-exited` card replaces the header line, and the exit token keeps the code visible after a reopen that missed the broadcast.

- [ ] **Step 5: Keep the walk's error object in `Service.qml`**

```diff
diff --git a/Service.qml b/Service.qml
index c3b8238..361ff7f 100644
--- a/Service.qml
+++ b/Service.qml
@@ -538,8 +538,9 @@ Item {
     for (var path in message.counts) counts[path] = message.counts[path]
     discoverCounts = counts
     var nextWalks = Object.assign({}, walks)
+    // `error` is the title, one fact in folder rows; `failure` keeps the object for the drive dialog.
     nextWalks[message.root] = {done: !!message.done, seconds: typeof message.seconds === "number" ? message.seconds : null,
-      error: errorText(message.error)}
+      error: errorText(message.error), failure: Errors.wrap(message.error)}
     if (message.error) folderError = Errors.wrap(message.error)
     if (Array.isArray(message.datasets)) {
       var nextSets = Object.assign({}, datasets)
```

`FolderTree.qml`, `Setup.scanFacts`, `Setup.walkError` and `requestChildren` keep reading the title string in `error`.

- [ ] **Step 6: Search banner slot, disk banner and preview errors in `SearchView.qml`**

```diff
diff --git a/SearchView.qml b/SearchView.qml
index 8e82224..aa61424 100644
--- a/SearchView.qml
+++ b/SearchView.qml
@@ -10,6 +10,7 @@ import "lib/results.js" as Results
 import "lib/searchState.js" as SearchState
 import "lib/Update.js" as Update
 import "lib/volumes.js" as Volumes
+import "lib/errors.js" as Errors

 // The search overlay body: query row, banner, result list, preview and footer.
 Item {
@@ -45,14 +46,40 @@ Item {
   readonly property bool daemonDown: !service || (!service.ready && !!connection
     && (connection.unit === "missing" || connection.failures > 0))
   // Set while Service.qml brings the daemon to the plugin's build (issue #16).
-  readonly property var updateBanner: service && service.update ? Update.banner(service.update) : null
-  // Service.qml turns `degraded` and a failed warm-up into error objects.
-  readonly property var degradedError: reply && reply.degraded ? reply.degraded
-    : service && service.searchError ? service.searchError : null
+  readonly property var updateError: service && service.update ? Update.banner(service.update) : null
+  readonly property var bannerView: Results.bannerFor({update: updateError,
+    offline: daemonDown ? Errors.offline(startLog.loaded ? startLog.path : "") : null,
+    reply: reply, warm: service ? service.searchError : null})
+
+  function retryBanner() {
+    if (!service || !bannerView) return
+    switch (bannerView.retry) {
+    case "update":
+      service.retryUpdate()
+      break
+    case "connect":
+      service.checkUnit()
+      service.connectSocket()
+      break
+    case "warm":
+      service.warm()
+      break
+    default:
+      search = SearchState.reduce(search, {type: "typed", query: search.query, now: Date.now()}).state
+      arm(meaningTimer, SearchState.meaningDelay)
+    }
+  }
+
+  // A preview error stands in for the preview of its row, so the pane shows it as a card.
+  function previewFailed(message) {
+    if (message.for !== undefined || !selectedItem || message.id !== selectedItem.id) return
+    preview = {id: message.id, error: Errors.from(message)}
+  }

   signal closeRequested()
   signal toastRequested(string title, var tokens, bool error)
-  signal openStarted(var item, string how)
+  // `message` is the open request, kept so the failure toast can send it again.
+  signal openStarted(var item, string how, var message)

   function reset() {
     previewTimer.stop()
@@ -256,7 +283,7 @@ Item {
     if (pending || !service || !service.send(message)) return
     player.stop()
     flash = how === "open" ? "acc" : "sec"
-    openStarted(item, how)
+    openStarted(item, how, message)
   }

   function toggleProgress() {
@@ -340,6 +367,7 @@ Item {
     if (previewKey) previewTimer.restart()
     else previewTimer.stop()
   }
+  onDaemonDownChanged: if (daemonDown) startLog.reload()

   Connections {
     target: root.service
@@ -351,6 +379,7 @@ Item {
         if (message.editor) root.editorCommand = message.editor
       }
     }
+    function onItemFailed(message) { root.previewFailed(message) }
     function onStatusReceived(message) {
       var files = typeof message.files === "number" ? message.files : -1
       var before = root.lastFiles
@@ -376,6 +405,16 @@ Item {
     }
   }

+  // The daemon's startup log. The offline card links it once it exists.
+  FileView {
+    id: startLog
+    path: (Quickshell.env("XDG_DATA_HOME") || (Quickshell.env("HOME") || "") + "/.local/share")
+      + "/omafind/cache/logs/omafindd-start.log"
+    printErrors: false
+    watchChanges: true
+    onFileChanged: reload()
+  }
+
   Timer {
     id: wordsTimer
     interval: SearchState.wordsDelay
@@ -421,51 +460,32 @@ Item {
     onKeyPressed: event => root.handleKey(event)
   }

-  Parts.Banner {
+  Parts.ErrorCard {
     id: banner
+    objectName: "omafindSearchError"
     anchors.top: query.bottom
     anchors.left: parent.left
     anchors.right: parent.right
-    visible: !!root.updateBanner || root.daemonDown || !!root.degradedError
-      || (!!root.reply && root.reply.t === "error")
+    error: root.bannerView ? root.bannerView.error : null
+    visible: !!error
     height: visible ? implicitHeight : 0
-    action: root.updateBanner ? root.updateBanner.action : "Retry"
-    lead: root.updateBanner ? root.updateBanner.lead
-      : root.daemonDown ? "" : root.degradedError ? root.degradedError.title
-      : root.reply && root.reply.t === "error" ? root.reply.title || "" : ""
-    text: root.updateBanner ? root.updateBanner.text
-      : root.daemonDown ? "omafindd is not running. Run systemctl --user start omafind, then retry."
-      : root.degradedError ? root.degradedError.detail || ""
-      : root.reply && root.reply.t === "error" ? root.reply.detail || String(root.reply.reason || "") : ""
-    onTriggered: {
-      if (root.updateBanner) {
-        root.service.retryUpdate()
-      } else if (root.daemonDown) {
-        if (root.service) {
-          root.service.checkUnit()
-          root.service.connectSocket()
-        }
-      } else if (root.degradedError) {
-        root.service.warm()
-      } else {
-        root.search = SearchState.reduce(root.search, {type: "typed", query: root.search.query, now: Date.now()}).state
-        arm(meaningTimer, SearchState.meaningDelay)
-      }
-    }
+    retryHere: true
+    onRetry: root.retryBanner()
   }

   // Spec 6.5: indexing waits for disk space. The banner has no action; it clears on `resumed`.
   Parts.Banner {
     id: diskBanner
+    objectName: "omafindDiskBanner"
     readonly property var info: root.service && root.service.volumes ? Volumes.diskBanner(root.service.volumes) : null
     anchors.top: banner.bottom
     anchors.left: parent.left
     anchors.right: parent.right
     visible: !!info
     height: visible ? implicitHeight : 0
-    lead: info ? info.title : ""
+    lead: info && info.error ? info.error.title : ""
     tokens: info ? info.tokens.map(t => ({k: t.k, v: t.v, tone: "plain"})) : []
-    text: info ? info.text : ""
+    text: info && info.error ? info.error.detail : ""
     action: ""
   }

```

- [ ] **Step 7: Preview pane card in `ui/PreviewLayer.qml`**

```diff
diff --git a/ui/PreviewLayer.qml b/ui/PreviewLayer.qml
index ab2e6d3..e99f096 100644
--- a/ui/PreviewLayer.qml
+++ b/ui/PreviewLayer.qml
@@ -36,6 +36,8 @@ Item {
   readonly property bool playingHere: mine && player.playing
   // The daemon's preview picks the line the opener jumps to; actions name that line.
   readonly property var jump: preview && (kind === "text" || kind === "code") ? preview.jump : null
+  // A preview error from the daemon (`{id, error}`), shown in place of the media.
+  readonly property var failure: preview && preview.error ? preview.error : null
   // Set when Qt cannot decode the full image (for example a missing image plugin).
   property bool fullFailed: false
   onPreviewChanged: fullFailed = false
@@ -68,6 +70,7 @@ Item {

   Item {
     id: media
+    visible: !root.failure
     anchors.top: parent.top
     anchors.topMargin: Style.space(26)
     anchors.left: parent.left
@@ -544,6 +547,15 @@ Item {
     }
   }

+  ErrorCard {
+    objectName: "omafindPreviewError"
+    anchors.centerIn: media
+    width: Style.space(600)
+    compact: true
+    error: root.failure
+    visible: !!error
+  }
+
   Column {
     id: info
     anchors.top: media.bottom
```

`ui/PreviewPane.qml` needs no change: it hands any preview whose `id` matches to the layer (pinned by the new previewPane test).

- [ ] **Step 8: Open failure toast in `ui/Toast.qml` and `Overlay.qml`**

```diff
diff --git a/ui/Toast.qml b/ui/Toast.qml
index 37436d7..4f01544 100644
--- a/ui/Toast.qml
+++ b/ui/Toast.qml
@@ -13,8 +13,15 @@ PanelWindow {
   property var tokens: []
   property bool error: false
   property bool showing: false
+  // An error object from the daemon, shown as a compact card.
+  property var failure: null
+  // A toast whose error has a fix stays until it is dismissed or retried.
+  readonly property bool sticky: !!failure && !!failure.fix
+
+  signal retryRequested()

   function show(nextTitle, nextTokens, isError) {
+    failure = null
     title = nextTitle
     tokens = nextTokens || []
     error = isError === true
@@ -24,6 +31,24 @@ PanelWindow {
     hold.restart()
   }

+  function showError(next) {
+    if (!next) return
+    failure = next
+    title = next.title
+    tokens = []
+    error = true
+    if (!visible) screen = focusedScreen()
+    showing = true
+    visible = true
+    if (sticky) hold.stop()
+    else hold.restart()
+  }
+
+  function dismiss() {
+    hold.stop()
+    showing = false
+  }
+
   function focusedScreen() {
     var name = Hyprland.focusedMonitor ? String(Hyprland.focusedMonitor.name) : ""
     var screens = Quickshell.screens
@@ -43,8 +68,8 @@ PanelWindow {
   WlrLayershell.namespace: "omafind-toast"
   WlrLayershell.layer: WlrLayer.Overlay
   WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
-  // Clicks pass through to the windows below.
-  mask: Region {}
+  // Clicks pass through to the windows below, except on a toast that waits for its fix.
+  mask: Region { item: root.sticky ? card : null }

   Timer {
     id: hold
@@ -87,6 +112,7 @@ PanelWindow {
       spacing: Style.space(10)

       Row {
+        visible: !root.failure
         spacing: Style.space(8)

         Icon {
@@ -110,11 +136,30 @@ PanelWindow {
       }

       Facts {
-        visible: root.tokens.length > 0
+        visible: !root.failure && root.tokens.length > 0
         width: Math.min(implicitWidth, column.width)
         tokens: root.tokens
         fontSize: Style.font.bodySmall
       }
+
+      ErrorCard {
+        objectName: "omafindToastError"
+        width: column.width
+        compact: true
+        retryHere: true
+        error: root.failure
+        visible: !!error
+        onRetry: root.retryRequested()
+      }
+
+      ActionButton {
+        objectName: "omafindToastDismiss"
+        visible: root.sticky
+        anchors.right: parent.right
+        buttonHeight: Style.space(26)
+        text: "Dismiss"
+        onClicked: root.dismiss()
+      }
     }
   }
 }
```

```diff
diff --git a/Overlay.qml b/Overlay.qml
index 5fdaffa..f6f1265 100644
--- a/Overlay.qml
+++ b/Overlay.qml
@@ -5,6 +5,7 @@ import Quickshell.Wayland
 import qs.Commons
 import "." as Plugin
 import "ui" as Parts
+import "lib/errors.js" as Errors

 // The search overlay. The shell calls only open(payload) and close(), and reads `opened` to toggle.
 Item {
@@ -207,8 +208,8 @@ Item {
         pending: root.pendingOpen
         onCloseRequested: root.dismiss()
         onToastRequested: (title, tokens, error) => toast.show(title, tokens, error)
-        onOpenStarted: (item, how) => {
-          root.pendingOpen = {id: item.id, how: how, item: item, reply: null, closed: false}
+        onOpenStarted: (item, how, message) => {
+          root.pendingOpen = {id: item.id, how: how, item: item, message: message, reply: null, closed: false}
           openTimeout.restart()
           closeTimer.restart()
         }
@@ -271,6 +272,8 @@ Item {
   }

   property var pendingOpen: null
+  // The last open that failed, so the toast's Retry can send it again.
+  property var failedOpen: null

   function announce() {
     var pending = pendingOpen
@@ -286,13 +289,26 @@ Item {
     pendingOpen = null
   }

-  function failOpen(reason) {
-    var name = pendingOpen.item.name
+  function failOpen(error) {
+    var failed = pendingOpen
     closeTimer.stop()
     openTimeout.stop()
     searchView.flash = ""
     pendingOpen = null
-    toast.show("Could not open " + name, [{k: "reason", v: reason, tone: "warn"}], true)
+    failedOpen = {message: failed.message, item: failed.item, how: failed.how}
+    toast.showError(error)
+  }
+
+  // The reply to a retried open is announced as a first open is.
+  function retryOpen() {
+    var failed = failedOpen
+    failedOpen = null
+    toast.dismiss()
+    if (!failed || !failed.message || !service || !service.send(failed.message)) return
+    pendingOpen = {id: failed.item.id, how: failed.how, item: failed.item, message: failed.message,
+      reply: null, closed: !opened}
+    openTimeout.restart()
+    if (opened) closeTimer.restart()
   }

   Connections {
@@ -304,10 +320,11 @@ Item {
       if (root.pendingOpen.closed) root.announce()
     }
     function onOpenFailed(message) {
-      if (root.pendingOpen && message.id === root.pendingOpen.id) root.failOpen(message.reason)
+      if (root.pendingOpen && message.id === root.pendingOpen.id) root.failOpen(Errors.from(message))
     }
     function onItemFailed(message) {
-      if (root.pendingOpen && message.for === "open" && message.id === root.pendingOpen.id) root.failOpen("error")
+      if (root.pendingOpen && message.for === "open" && message.id === root.pendingOpen.id)
+        root.failOpen(Errors.from(message))
     }
   }

@@ -328,5 +345,6 @@ Item {

   Parts.Toast {
     id: toast
+    onRetryRequested: root.retryOpen()
   }
 }
```

- [ ] **Step 9: Setup header, Folders step and Index step**

```diff
diff --git a/ui/SetupHeader.qml b/ui/SetupHeader.qml
index a0e9e62..8644ac3 100644
--- a/ui/SetupHeader.qml
+++ b/ui/SetupHeader.qml
@@ -10,7 +10,6 @@ Item {
   property string crumbLeaf: ""
   property string title: ""
   property string subtitle: ""
-  property color subtitleColor: Plugin.Tokens.dim
   property var facts: []
   property bool spinning: false
   property string stepText: ""
@@ -73,7 +72,7 @@ Item {
         text: root.subtitle
         textFormat: Text.PlainText
         elide: Text.ElideRight
-        color: root.subtitleColor
+        color: Plugin.Tokens.dim
         font.family: Style.font.family
         font.pixelSize: Style.font.body
       }
```

```diff
diff --git a/SetupView.qml b/SetupView.qml
index db0f97a..71794a8 100644
--- a/SetupView.qml
+++ b/SetupView.qml
@@ -25,8 +25,7 @@ FocusScope {
     + (step === 1 ? enginePage.extraHeight : 0)
   readonly property string walkError: service ? Setup.walkError(service.walks) : ""
   readonly property var discover: service ? service.discover : null
-  readonly property string indexFailure: step === 3 && service ? Setup.indexFailure(service.progress,
-    service.indexError ? (service.indexError.title + " " + service.indexError.detail).trim() : "") : ""
+  readonly property var indexFailure: step === 3 && service ? service.indexError : null
   readonly property string home: discover && discover.home ? discover.home : (Quickshell.env("HOME") || "")


@@ -119,12 +118,8 @@ FocusScope {
             : Setup.indexTitle(root.service ? root.service.progress : null, root.indexFailure)
           stepText: Setup.stepLabel(root.step)
           subtitle: root.step === 1 ? "Everything runs on this machine. Nothing downloads until you press a button."
-            : root.step === 3 ? root.indexFailure || "You can search already. Results fill in as files finish."
-            : root.service && !root.service.scanning && root.service.folderError
-              ? (root.service.folderError.title + " " + root.service.folderError.detail).trim()
-            : root.walkError !== "" ? Setup.folderError(root.walkError)
+            : root.step === 3 ? "You can search already. Results fill in as files finish."
             : ""
-          subtitleColor: root.step === 2 || root.indexFailure !== "" ? Color.urgent : Plugin.Tokens.dim
           spinning: root.step === 2 && !!root.service && (root.service.scanning
             || Object.keys(root.service.walks).some(key => !root.service.walks[key].done))
           facts: root.step !== 2 || !root.discover ? []
```

`walkError` stays a string (Task 6), so the rescan check in `showFolders` is unchanged.

```diff
diff --git a/ui/SetupFolders.qml b/ui/SetupFolders.qml
index c055c60..31a138f 100644
--- a/ui/SetupFolders.qml
+++ b/ui/SetupFolders.qml
@@ -23,6 +23,8 @@ FocusScope {
   readonly property var discover: service ? service.discover : null
   readonly property string home: discover && discover.home ? discover.home : (Quickshell.env("HOME") || "")
   readonly property var rates: discover ? discover.rates : null
+  // Step 2 shows its own error, else a failed start of the first index.
+  readonly property var failure: service ? service.folderError || service.indexError : null
   readonly property string device: discover && discover.device ? discover.device : "gpu"
   readonly property var folders: (discover && Array.isArray(discover.folders) ? discover.folders : []).concat(added)
   // Drives mounted inside another root, such as a disk under $HOME.
@@ -110,6 +112,12 @@ FocusScope {
     if (service) service.requestChildren(absolute)
   }

+  function retry() {
+    if (!service) return
+    if (service.folderError) service.scan()
+    else startIndexing()
+  }
+
   function startIndexing() {
     if (!ready) return
     service.startIndexing(roots, choices.code)
@@ -196,13 +204,13 @@ FocusScope {

     Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }

-    Label {
-      visible: !!root.service && !!root.service.indexError
+    ErrorCard {
+      objectName: "omafindFolderError"
       width: parent.width
-      wrapMode: Text.Wrap
-      text: root.service && root.service.indexError
-        ? (root.service.indexError.title + " " + root.service.indexError.detail).trim() : ""
-      color: Color.urgent
+      error: root.failure
+      visible: !!error
+      retryHere: true
+      onRetry: root.retry()
     }

     Item {
```

Step 2 shows `folderError`, else `indexError`: a failed `index_start` (for example `internal`) arrives before any progress, so the view is still on step 2. Retry scans again for a folder error and starts indexing again otherwise.

```diff
diff --git a/ui/SetupIndex.qml b/ui/SetupIndex.qml
index a810ec5..d6f11c7 100644
--- a/ui/SetupIndex.qml
+++ b/ui/SetupIndex.qml
@@ -2,6 +2,7 @@ import QtQuick
 import qs.Commons
 import ".." as Plugin
 import "../lib/setup.js" as Setup
+import "../lib/errors.js" as Errors
 import "../lib/keycombo.js" as Keycombo

 // Step 3 (board Indexing, M3 step 5): first index progress, skips and the global shortcut.
@@ -22,8 +23,13 @@ FocusScope {
   readonly property var rates: service && service.discover ? service.discover.rates : null
   readonly property var head: Setup.indexHead(progress, rates)
   readonly property var problems: progress && progress.problems ? progress.problems : []
-  // The problem list grows the panel instead of scrolling inside it, up to eight rows.
-  readonly property real extraHeight: showList && problems.length ? list.height + Style.space(8) : 0
+  readonly property var indexError: service ? service.indexError : null
+  readonly property var toolErrors: progress && Array.isArray(progress.tool_errors) ? progress.tool_errors : []
+  // The problem list (up to eight rows) and the error cards grow the panel instead of scrolling inside it.
+  readonly property real extraHeight: (showList && problems.length ? list.height + Style.space(8) : 0)
+    + (cards.visible ? cards.height + Plugin.Tokens.setupGap : 0)
+    + (bindsCard.visible ? bindsCard.height + Plugin.Tokens.setupGap : 0)
+    + (saveCard.visible ? saveCard.height + Plugin.Tokens.setupGap : 0)
   readonly property var bindMap: service ? Keycombo.bindMap(service.binds) : ({})
   readonly property bool bindsKnown: !!service && (service.bindsReady || !!service.bindsError)
   readonly property var chosenParts: Keycombo.fromHyprland(chosen)
@@ -58,6 +64,11 @@ FocusScope {
     })
   }

+  // Retry on the index card starts the saved roots again.
+  function retryIndex() {
+    if (service) service.startIndexing(service.settings.roots, service.settings.codeRoots)
+  }
+
   Column {
     width: parent.width
     spacing: Plugin.Tokens.setupGap
@@ -168,14 +179,41 @@ FocusScope {
             required property var modelData
             width: Math.min(implicitWidth, problemColumn.width)
             fontSize: Style.font.bodySmall
-            tokens: [
-              {k: modelData.reason, v: Setup.displayPath(modelData.path, root.service && root.service.discover ? root.service.discover.home : ""), tone: "plain"}
-            ]
+            tokens: Setup.problemTokens(modelData, root.service && root.service.discover ? root.service.discover.home : "")
           }
         }
       }
     }

+    Column {
+      id: cards
+      visible: !!root.indexError || root.toolErrors.length > 0
+      width: parent.width
+      spacing: Style.space(8)
+
+      ErrorCard {
+        objectName: "omafindIndexError"
+        width: parent.width
+        error: root.indexError
+        visible: !!error
+        retryHere: true
+        onRetry: root.retryIndex()
+      }
+
+      // A count model keeps each card, and its install polling, alive across progress updates.
+      Repeater {
+        model: root.toolErrors.length
+
+        delegate: ErrorCard {
+          required property int index
+          objectName: "omafindToolError"
+          width: cards.width
+          error: root.toolErrors[index] || null
+          onRetry: if (root.service) root.service.retryFailed("tool-missing")
+        }
+      }
+    }
+
     Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }

     Column {
@@ -212,7 +250,6 @@ FocusScope {
         || (recorder.lost ? "Hyprland left recording mode, so omafind stopped recording. Press Change to try again." : "")
         || (recorder.exposed ? "Hyprland could not enter recording mode. Press Change to try again." : "")
         || root.chosenConflict
-        || (root.service && root.service.bindsError ? root.service.bindsError.title + " The shortcut has not been checked for conflicts. Close setup and open it again to retry." : "")
       noteTone: note !== "" ? "warn" : ""
       onChange: {
         recorder.start()
@@ -222,6 +259,16 @@ FocusScope {
       onCaptured: (key, modifiers) => recorder.capture(key, modifiers)
     }

+    ErrorCard {
+      id: bindsCard
+      objectName: "omafindBindsError"
+      width: parent.width
+      error: root.service ? root.service.bindsError : null
+      visible: !!error
+      retryHere: true
+      onRetry: if (root.service) root.service.getBinds()
+    }
+
     ShortcutRecorder {
       id: recorder
       binds: root.bindMap
@@ -266,15 +313,12 @@ FocusScope {
     width: parent.width
     spacing: Plugin.Tokens.setupGap

-    Label {
-      visible: root.saveError !== ""
+    ErrorCard {
+      id: saveCard
+      objectName: "omafindSaveError"
       width: parent.width
-      wrapMode: Text.Wrap
-      text: root.saveError
-      textFormat: Text.PlainText
-      color: Color.urgent
-      font.family: Style.font.family
-      font.pixelSize: Style.font.bodySmall
+      error: Errors.wrap(root.saveError)
+      visible: !!error
     }

     Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }
```

The tool-missing cards keep `retryHere` off: their poll emits `retry` once the package is present, and that sends `retry_failed`.

- [ ] **Step 10: Drive dialog in `ui/DriveDialog.qml`**

```diff
diff --git a/ui/DriveDialog.qml b/ui/DriveDialog.qml
index f3bede1..5015146 100644
--- a/ui/DriveDialog.qml
+++ b/ui/DriveDialog.qml
@@ -38,8 +38,7 @@ FocusScope {
   readonly property bool anyChecked: choices.chosen.length > 0
   readonly property var progress: service ? service.progress : null
   readonly property var footer: Volumes.dialogFooter(progress, uuid, label)
-  readonly property var failure: service ? service.driveError || service.indexError : null
-  readonly property string errorText: failure ? (failure.title + " " + failure.detail).trim() : walk ? walk.error : ""
+  readonly property var failure: driveFailure()

   readonly property real panelWidth: Style.space(1120)
   // The 4 covers the card border on both edges.
@@ -58,6 +57,18 @@ FocusScope {
     if (service && uuid) service.scanDrive(uuid)
   }

+  // The dialog's one error: its own request's, the drive walk's, then the drive's index run.
+  function driveFailure() {
+    if (!service) return null
+    return service.driveError || (walk && walk.failure ? walk.failure : null)
+      || (phase === "run" ? service.indexError : null)
+  }
+
+  function retry() {
+    if (phase === "run") startIndexing()
+    else begin()
+  }
+
   function focusFirst() {
     if (tree.focusFirst()) return
     if (start.enabled) start.forceActiveFocus()
@@ -231,15 +242,13 @@ FocusScope {
         tokens: [{k: "watch", v: "off · removable", tone: "plain"}, {k: "reconcile", v: "on mount", tone: "plain"}]
       }

-      Label {
-        visible: root.errorText !== ""
+      ErrorCard {
+        objectName: "omafindDriveError"
         width: parent.width
-        wrapMode: Text.Wrap
-        text: root.errorText
-        textFormat: Text.PlainText
-        color: Color.urgent
-        font.family: Style.font.family
-        font.pixelSize: Style.font.bodySmall
+        error: root.failure
+        visible: !!error
+        retryHere: true
+        onRetry: root.retry()
       }

       // `.fx-bot`: the totals and buttons cross-fade to the drive's progress over 180 ms.
```

- [ ] **Step 11: Run the full checks**

```bash
uv run --project helper pytest -q
node --test "tests/js/*.test.mjs"
uv run --project helper ruff check helper tests bin/omafind scripts evals
scripts/qmllint.sh
git diff --check
```

All five pass (integration run: `1039 passed`, JS `260` pass). `grep -rn "setupError\|discoverError\|warmFailure\|degradedReason\|updateBanner\|degradedError\|subtitleColor\|indexFailure(\|folderError(" --include=*.qml --include=*.js .` prints nothing outside `docs/`. `errorText` remains only as Task 6's helper in `Service.qml`.

- [ ] **Step 12: Fake-home harness check**

The repo has no harness script. Run this check list by hand with an offscreen harness, as in earlier issues: no key injection, no change to the live plugin link or `~/.config/omarchy/shell.json`.

Setup, in the session scratchpad (`$S` below):
1. `mkdir -p $S/harness/bin`; `ln -s /usr/share/omarchy/shell/Commons $S/harness/Commons`; `ln -s <worktree> $S/harness/plugin`.
2. PATH stubs in `$S/harness/bin`, each `#!/bin/sh` that appends `"$0 $*"` to `$S/harness/argv.log`: `omarchy-launch-editor`, `omarchy-launch-floating-terminal-with-presentation`, `wl-copy`. `omarchy-pkg-present` logs, then exits 0 only when `$S/harness/present` exists.
3. `$S/harness/shell.qml`: a `FakeService` `Item` with the Service.qml surface the views read (`ready`, `connection`, `update`, `status`, `volumes`, `clock`, `progress`, `settings`, `walks` (entries `{done, seconds, error, failure}`: `error` is the title string, `failure` the object), `childFolders`, `discover`, `binds`, `bindsReady`, `bindsError`, `folderError`, `indexError`, `driveError`, `searchError`, `indexPending`, `scanning`, `driveScanning`, `driveDiscover`, signals `resultsReceived`, `previewReceived`, `itemFailed`, `statusReceived`, `volumesRefreshed`), with call counters for `warm`, `scan`, `scanDrive`, `getBinds`, `retryUpdate`, `checkUnit`, `connectSocket`, `retryFailed`, `startIndexing`, `send`. It loads `plugin/SearchView.qml`, `plugin/SetupView.qml`, `plugin/ui/DriveDialog.qml` and `plugin/ui/Toast.qml`, plus the DriveToast stub that the setup view needs offscreen. A `Timer` steps through the cases below, finds each card with a recursive `objectName` walk, presses buttons by calling the `ActionButton`'s `clicked()` signal whose `text` matches, saves `grabToImage` PNGs to `$S/harness/shots/`, then calls `Qt.quit()`.
4. Run it once, capped (one quickshell at a time, never next to a build or `llama-server`):
   ```bash
   QT_QPA_PLATFORM=offscreen PATH=$S/harness/bin:$PATH \
     systemd-run --user --scope --quiet --collect -p MemoryMax=2G -p MemorySwapMax=0 -- \
     quickshell -p $S/harness/shell.qml > $S/harness/log.txt 2>&1
   ```
   Then `grep -E "unavailable|Invalid|Cannot read|ReferenceError|TypeError|is not a function" $S/harness/log.txt` prints nothing, and `pgrep -x quickshell` lists only the live shell's PID.

Checks (each one is a step in the harness `Timer` plus a PNG):
- [ ] `omafindSearchError` with `searchError` = `server-start-failed` with `log`: red wash, title and detail, "Open log" and "Retry". Retry: `warm` count goes up by 1. Open log: `argv.log` gains `omarchy-launch-editor <log>`.
- [ ] `results.degraded` = `server-starting` (send a `results` reply through `resultsReceived` for the current seq): yellow wash, no buttons. Footer reads `… · keyword matches only`.
- [ ] Daemon offline (`ready: false`, `connection: {unit: "missing", failures: 1}`): the card title is "The omafind service is not running.". Retry: `checkUnit` and `connectSocket` each go up by 1. Create `$XDG_DATA_HOME/omafind/cache/logs/omafindd-start.log` in the fake home and the card gains "Open log".
- [ ] `update.phase` `updating`: yellow card, no button. `failed` with `error: "uv sync failed"`: red card with Retry, and Retry raises `retryUpdate` by 1. The update card replaces any degraded card.
- [ ] A `t:"error"` reply with `seq` and code `no-index`: red card, no Retry button (no fix).
- [ ] `omafindDiskBanner` after a `paused` event with the `disk-low` object: lead "Indexing is paused.", tokens `free 1.4 GB` and `needed 2 GB`, the detail after them, no button.
- [ ] `omafindPreviewError`: select a row, emit `itemFailed({t: "error", id: <selected id>, code: "file-missing", …})`. The compact card shows in the media area, the media is hidden, the name and actions stay.
- [ ] `omafindToastError`: `toast.showError(<open-failed with retry fix>)` shows the compact card and "Dismiss" (`omafindToastDismiss`). It is still showing after 4 s. Retry emits `retryRequested`, and Dismiss hides it. `showError(<file-missing, no fix>)` hides by itself after 2.8 s with no Dismiss.
- [ ] Setup step 2, `omafindFolderError`: `folderError` = `scan-failed`. Retry raises `scan` by 1. The header subtitle is empty and dim (no error text in the header). With `folderError` null and `indexError` = `internal` (retry fix), the same card shows it and Retry calls `startIndexing` once.
- [ ] Setup step 3: `indexError` = `index-exited` with `log`. `omafindIndexError` shows with Retry and Open log, and Retry calls `startIndexing` with the settings roots. The header title reads "Indexing stopped" and the subtitle "You can search already. Results fill in as files finish.". The panel grows by the card height, and the footer does not overlap the body.
- [ ] Step 3 with `progress.tool_errors` holding two `tool-missing` objects: two `omafindToolError` cards with "Install packages" and the `sudo pacman -S --needed tesseract` line. Install packages: `argv.log` gains `omarchy-launch-floating-terminal-with-presentation omarchy-pkg-add tesseract`. Send a new `progress` object while the card is installing: the card keeps "Installing in the terminal", and "Install packages" stays visible (Task 6). `touch $S/harness/present`: within 2 s `retryFailed("tool-missing")` is called once.
- [ ] Step 3 with `progress.problems` of the new shape, then "Show list": rows read `encrypted-pdf pdfinfo failed: Incorrect password  path ~/Documents/a.pdf`.
- [ ] Step 3, `bindsError` = `binds-failed`: `omafindBindsError` shows with Retry, and Retry raises `getBinds` by 1. The shortcut note has no binds sentence.
- [ ] Drive dialog, `driveError` = `drive-not-mounted`: `omafindDriveError` shows with Retry, and Retry raises `scanDrive` by 1. With `driveError` null and `walks[<mount>].failure` = `scan-failed`, the card shows the walk's object. In phase `run` with `indexError` set, Retry calls `startIndexing` with the drive UUID.
- [ ] Every PNG: red cards use the `Color.urgent` wash and yellow cards the `Palette.yellow` wash, with no hard-coded color (`grep -nE "#[0-9a-fA-F]{3,8}" ui/*.qml *.qml` finds no new literal).

List these checks, and the strings this task adds ("Dismiss", the two update titles and details), in the pull request for review.

- [ ] **Step 13: Commit**

```bash
git add lib/results.js lib/Update.js lib/volumes.js lib/setup.js \
  Service.qml SearchView.qml Overlay.qml SetupView.qml \
  ui/SetupHeader.qml ui/SetupFolders.qml ui/SetupIndex.qml ui/DriveDialog.qml ui/Toast.qml \
  ui/PreviewLayer.qml \
  tests/js/overlay.test.mjs tests/js/searchView.test.mjs tests/js/results.test.mjs \
  tests/js/update.test.mjs tests/js/volumes.test.mjs tests/js/setup.test.mjs \
  tests/js/driveDialog.test.mjs tests/js/previewPane.test.mjs \
  tests/js/serviceDiscovery.test.mjs tests/js/shortcutSetup.test.mjs \
  tests/fixtures/results/degraded.json tests/fixtures/setup/progress.json
git status --short
git diff --staged --stat
git commit -S -m "fix(overlay): show every error with one card"
```

---

### Task 8: Docs

**Files:**
- Modify: `docs/ipc.md`
- Modify: `docs/DESIGN.md`
- Modify: `README.md`

The diffs below are against the tree after Tasks 1 to 7. Those tasks touch no docs, so these three files still equal `4925220`. Apply each with `git apply`; if one does not apply, match each hunk by its before text, not by line number.

AGENTS.md rule check: `retry_failed` is a new message and no settings key is added. `docs/ipc.md` gets the row. `settings.example.json`, `helper/omafindd/settings.py` and `lib/Settings.js` do not change. The README has no messages table (its tables are status exit codes, `status --json` fields and settings keys); it links to `docs/ipc.md`, so it needs no `retry_failed` row. No README table lists a `reason` field.

**Interfaces:** Consumes, exactly as shipped by Tasks 1 to 7:
- Task 1: the `UserError` fields (`code`, `title`, `detail`, optional `fix`, optional `log`), `fix` kinds `{"kind":"install","packages":[...]}` and `{"kind":"retry"}`, and the copy of every constructor in `helper/omafindd/errors.py`. The Errors table below matches every constructor's title, detail and fix kind.
- Task 2: `index_running()` (`index-running`, yellow); `runtime_progress.error`, `warm_failed.error`, `results.degraded`, `open_failed.error`, `paused.error`, `discover_counts.error`, `discover_children.error`, `fs_list.error` as objects; `t:"error"` with `for` / `seq` / `id` plus the object fields; index exit as `index-exited` with `log`. `open_failed` carries `drive-not-mounted`, `file-missing` or `open-failed` (the opener failed to start); an open `error` reply carries `bad-request` or `internal`. A drive scan whose drive is gone replies `drive-not-mounted`.
- Task 3: `paths.logs_dir()` = `<data>/cache/logs`; `build-runtime.log`, `omafindd-start.log`; `tools.BUILD_NEEDS`; `bin/omafind setup --json` last line `{"ok":true,"build_missing":[...]}` or `{"ok":false,"error":{...}}`. Setup fails only on missing runtime tools (`tools-missing`) or a failed step or silent socket (`helper-install-failed`); missing build packages only add a stderr note and `build_missing`. `status` lists build packages under `tools.missing` while the runtime binary is missing and exits 1 for any missing tool. `build-runtime` and the daemon's install job stop before the build with `build-missing-packages`.
- Task 4: `llama-server.log`; start cause "It did not answer within 60 s" or "It exited with code N" plus the log's last error line.
- Task 5: `progress.problems` items `{path, code, detail}`, `progress.failed` `{code: count}`, `progress.tool_errors` (list of `tool-missing` objects, `[]` when none), request `{"t":"retry_failed","code":"tool-missing"}` and reply `{"t":"retry_failed","code":"tool-missing","count":n}`. Audio off and silent audio are the codes `audio-off` and `silent-audio`; an encrypted PDF has detail `""`.
- Task 6: `lib/errors.js` (`wrap`, `tone` returning `warn` or `urgent`, `installCommand`, `offline`), `ui/ErrorCard.qml` (buttons "Install packages", "Open log", "Retry", "Copy"; `compact`; Install packages stays pressable while it waits; Retry shows for a retry or install fix where the view sets `retryHere`), `Banner.qml` as a wrapper, step 1 labels Install, Pause, Retry, Resume, Next: pick folders.
- Task 7: where each card appears; the open toast that stays while its error has a fix, with "Dismiss"; the `update-running` and `update-failed` errors in `lib/Update.js`.

Facts confirmed in the code after Tasks 1 to 7; the diffs assume them. Rerun these before applying and, if one differs, change the doc text to match the code:

```bash
grep -n "errors\.\w*(" helper/omafindd/setup.py helper/omafindd/install.py helper/omafindd/ipc.py helper/omafindd/service.py helper/omafindd/discovery.py
grep -n "tool_errors\|missing_tools\|retry_failed" helper/omafindd/setup.py helper/omafindd/indexing.py
grep -n "reason_code" helper/omafindd/*.py lib/*.js ui/*.qml
grep -n "audio search is off\|silent audio\|audio-off\|silent-audio" helper/omafindd/*.py
```

1. The install job raises `build-missing-packages`, `build-failed`, `build-no-scope`, `model-download-failed`, `model-verify-failed` or `internal`, never `tools-missing`.
2. `progress` has `tool_errors` and no `missing_tools`.
3. `fs_list` has no `reason_code`.
4. Audio off and silent audio are the codes `audio-off` and `silent-audio`, so the README and `docs/ipc.md` say "code", not "detail".

- [ ] **Step 1: Edit `docs/ipc.md`**

What changes: the update flow names the `update-running` card. A new `## Errors` section goes before `## Search and warm-up (issue #2)`: object shape, fix kinds, the three places an error travels, tone, the code table with the four plugin-written codes (`daemon-offline`, `update-running`, `update-failed`, `unknown`), and `setup --json`. The `warm`, reindex lock, cold server, `degraded` and search error text uses error objects. The audio lines name codes. The `preview`, `open_failed` and open `error` rows change, and the setup request table gains `retry_failed`. Also: `runtime_progress.error` and its codes, walk, children and `fs_list` failures, the `progress` example, the per-file and `tool_errors` bullets, index exit, setup error codes plus the `retry_failed` exchange, the `paused` and drive `progress` examples, and model verification.

````diff
diff --git a/docs/ipc.md b/docs/ipc.md
index 901c798..216bc61 100644
--- a/docs/ipc.md
+++ b/docs/ipc.md
@@ -27,7 +27,77 @@ The scaffold implements the proposed state shape and push-on-change behavior. `r

 `build` is the fingerprint of the plugin code the daemon started from: the manifest version, `+`, then the first 12 hex digits of a sha256 over `helper/uv.lock`, `helper/pyproject.toml` and every `helper/omafindd/**/*.py`. It does not change while the daemon runs. `bin/omafind fingerprint` prints the same value for a plugin checkout.

-`Service.qml` runs `bin/omafind fingerprint` once when the plugin loads. When a `state` carries a different `build`, or none (a daemon older than this field), it runs `bin/omafind setup` once for that plugin build. A daemon that exits on a missing dependency sends no `state`, so after the third failed connect `Service.qml` runs `bin/omafind status --json` and treats a `stale` or `missing` venv the same way. A daemon that cannot fingerprint its own code reports `build:""`. Setup syncs the venv to the lock file and restarts the unit, and the plugin reconnects. While setup runs, the search view shows "Updating omafindd to match the installed plugin. Search returns when it restarts." If setup fails, it shows the last stderr line once, as "omafindd did not update: <line>. Press Retry to run bin/omafind setup again." It runs setup again only on Retry or for a newer plugin build. A `state` with the plugin's build clears the failure.
+`Service.qml` runs `bin/omafind fingerprint` once when the plugin loads. When a `state` carries a different `build`, or none (a daemon older than this field), it runs `bin/omafind setup` once for that plugin build. A daemon that exits on a missing dependency sends no `state`, so after the third failed connect `Service.qml` runs `bin/omafind status --json` and treats a `stale` or `missing` venv the same way. A daemon that cannot fingerprint its own code reports `build:""`. Setup syncs the venv to the lock file and restarts the unit, and the plugin reconnects. While setup runs, the search view shows an `update-running` card ("omafindd is updating to match the installed plugin."). Setup runs as `bin/omafind setup --json`, whose last stdout line is `{"ok":true}` or `{"ok":false,"error":{...}}` (see Errors). If setup fails, the search view shows that error once, with Retry. It runs setup again only on Retry or for a newer plugin build. A `state` with the plugin's build clears the failure.
+
+## Errors
+
+Every failure the plugin shows is one error object. The daemon writes its copy in `helper/omafindd/errors.py`, one constructor per code.
+
+```json
+{"code":"build-missing-packages","title":"The search engine could not be built.","detail":"Missing build packages: vulkan-headers. Install them, then press Retry.","fix":{"kind":"install","packages":["vulkan-headers"]},"log":"/home/u/.local/share/omafind/cache/logs/build-runtime.log"}
+```
+
+| Field | Value |
+|---|---|
+| `code` | Stable kebab-case string. The plugin branches on it, never on the text. |
+| `title` | One sentence: what happened. |
+| `detail` | One or two sentences: why, then what to do next. It names plugin controls ("press Retry"), never CLI commands. May be `""`. |
+| `fix` | Optional. `{"kind":"install","packages":[...]}` or `{"kind":"retry"}`. |
+| `log` | Optional. Absolute path of the log that holds the full cause. |
+
+The object has no other fields. Facts a view shows as tokens, such as `free_gb` or a file count, stay on the message that carries the object.
+
+- `fix.kind:"install"`: `packages` are Arch repository names without duplicates. The plugin offers Install packages, which runs `omarchy-launch-floating-terminal-with-presentation omarchy-pkg-add <packages>`, and shows `sudo pacman -S --needed <packages>` with Copy. It then runs `omarchy-pkg-present <packages>` every 2 s for up to 10 minutes and retries when it succeeds. Install packages stays pressable while it waits, to open the terminal again. Retry, a new code, a cleared error or a closed view stops the wait.
+- `fix.kind:"retry"`: the view's own retry control is the fix. Step 1 of setup uses its footer button, labelled Retry. Every other card (search banner, Folders and Index steps, drive dialog, open toast) puts Retry on the card, also next to an install fix, whose detail says "then press Retry". An open toast whose error has a fix stays until Retry or Dismiss.
+- `log`: the plugin offers Open log, which runs `omarchy-launch-editor <log>`. Logs live in `<data>/cache/logs/` (`build-runtime.log`, `llama-server.log`, `omafindd-start.log`) and at `<data>/index/reindex.log`. `<data>` is `$XDG_DATA_HOME/omafind`, by default `~/.local/share/omafind`.
+
+An error travels in one of three places:
+
+- A `{"t":"error",...}` reply or broadcast. The object's fields sit at the top level next to the routing key: `for` (setup requests and `open`), `seq` (search) or `id` (preview and open).
+- A field named `error` on `runtime_progress`, `warm_failed`, `open_failed`, `paused`, `discover_counts`, `discover_children` and `fs_list`, and each item of `progress.tool_errors`.
+- `results.degraded`.
+
+`code` follows the cause, not the request that hit it. An exception no handler expects becomes `internal`, with the exception text as the cause.
+
+Tone is the card color: red (`Color.urgent`) for a failure, yellow (`Palette.yellow`) for a degraded or paused state. `tone()` in `lib/errors.js` returns `urgent` or `warn`. `<cause>` is one clause from the failing call (an HTTP status and message, an OS error, the first error line of a log), at most 200 characters and never a secret. The tests pin the copy rules, not these strings; `errors.py` wins when they differ.
+
+| Code | Tone | Title | Detail | Fix | Log |
+|---|---|---|---|---|---|
+| `tools-missing` | red | Some tools omafind needs are missing. | Missing: `<packages>`. Install them, then press Retry. | install | |
+| `helper-install-failed` | red | The omafind helper could not be installed. | `<cause>`. Press Retry to try again. | retry | |
+| `build-missing-packages` | red | The search engine could not be built. | Missing build packages: `<packages>`. Install them, then press Retry. | install | `build-runtime.log` |
+| `build-failed` | red | The search engine could not be built. | `<first error line>`. Open the log for the full output, then press Retry. | retry | `build-runtime.log` |
+| `build-no-scope` | red | The search engine could not be built safely. | The systemd user memory scope is unavailable, so the build would run without a memory cap. Log out and back in, then press Retry. | retry | |
+| `model-download-failed` | red | The model could not be downloaded. | `<cause>`. Check the network connection, then press Retry. | retry | |
+| `model-verify-failed` | red | The downloaded model is damaged. | `<file>` does not match its checksum. Press Retry to download it again. | retry | |
+| `server-start-failed` | red | The embedding server did not start. | `<cause>`. Showing keyword matches until it starts. | retry | `llama-server.log` when known |
+| `server-starting` | yellow | The embedding server is starting. | Showing keyword matches until it is ready. | | |
+| `embedding-unavailable` | yellow | Search by meaning is unavailable. | `<cause>`. Showing keyword matches. | retry | `llama-server.log` when known |
+| `index-running` | yellow | Indexing is running. | Showing keyword matches until it finishes. | | |
+| `disk-low` | yellow | Indexing is paused. | Free some disk space and indexing resumes by itself. | | |
+| `index-exited` | red | Indexing stopped. | The indexer exited with code `<n>`. Open the log for the cause, then press Retry. | retry | `index/reindex.log` |
+| `no-roots` | red | No folders are selected. | Pick at least one folder to index. | | |
+| `drive-not-mounted` | red | `<drive>` is not connected. | Connect it, then press Retry. | retry | |
+| `scan-failed` | red | `<folder>` could not be scanned. | `<cause>`. Press Retry to scan it again. | retry | |
+| `binds-failed` | red | Your Hyprland bindings could not be read. | `<cause>`. The shortcut was not saved. | retry | |
+| `no-index` | red | Nothing is indexed yet. | Open setup and start the first index. | | |
+| `file-missing` | red | `<name>` is missing. | It was moved or deleted after it was indexed. | | |
+| `open-failed` | red | `<name>` could not be opened. | `<cause>`. | retry | |
+| `tool-missing` | red | `<n>` files need `<tool>`. (1 file needs `<tool>`.) | They were indexed without `<what>`. Install `<package>` and they are indexed again. | install | |
+| `bad-request` | red | omafind sent a request the service did not understand. | `<cause>`. Restart the overlay and try again. | | |
+| `internal` | red | Something failed inside the omafind service. | `<cause>`. | retry | |
+| `daemon-offline` (plugin) | red | The omafind service is not running. | It did not answer on its socket. Press Retry to start it. | retry | `omafindd-start.log` when it exists |
+| `update-running` (plugin) | yellow | omafindd is updating to match the installed plugin. | Search returns when it restarts. | | |
+| `update-failed` (plugin) | red | omafindd did not update. | `<setup error>`. Press Retry to try again. | retry | |
+| `unknown` (plugin) | red | `<string>` | `""` | | |
+
+The plugin writes copy for four codes only, because no daemon reply exists for them:
+
+- `daemon-offline` (`lib/errors.js`): the socket does not answer. Its Open log points at `omafindd-start.log`, which the daemon writes when it fails to start (a failed import or socket bind) and removes once its socket is up.
+- `update-running` and `update-failed` (`lib/Update.js`): `bin/omafind setup` is bringing the daemon to the plugin's build, or it failed. The daemon is restarting, so it cannot write the copy.
+- `unknown`: a daemon older than this section. During an update a new plugin can briefly talk to a daemon that still sends a bare string (`reason`, or a string `degraded` or `error`). The plugin wraps it as `{"code":"unknown","title":"<string>","detail":""}`. The daemon restarts with the plugin update, so this lasts until then.
+
+`bin/omafind setup --json` prints `{"ok":true,"build_missing":[...]}` or `{"ok":false,"error":{...}}` as its last stdout line. Setup fails only with `tools-missing` (a runtime tool is missing) or `helper-install-failed` (a setup step failed, or the socket stayed silent). Missing build packages never fail setup: while the runtime binary is missing, `build_missing` lists them and stderr says so, and the engine step reports `build-missing-packages` before it builds.

 ## Search and warm-up (issue #2)

@@ -39,15 +109,15 @@ These shapes are proposed. After `hello`, a connection may send:
 ```

 `warm` starts the text-mode embedder and replies with the current `state`, or
-`{"t":"warm_failed","reason":"Vulkan device lost"}`.
+`{"t":"warm_failed","error":{"code":"server-start-failed","title":"The embedding server did not start.","detail":"It did not answer within 60 s. Showing keyword matches until it starts.","fix":{"kind":"retry"},"log":"/home/u/.local/share/omafind/cache/logs/llama-server.log"}}`.
 After `warmMinutes` without a query the embedder stops. Each query resets this
 timeout. `warmMinutes:0` stops it immediately after the reply.

 The CLI holds an exclusive lock on `~/.local/share/omafind/index.lock` during
 reindex. The daemon probes it with a non-blocking shared flock before starting
 a server. While reindex holds the lock, all searches use `legs:["words"]` and
-`degraded:"indexing in progress"`, including requests for meaning only.
-`warm` replies `{"t":"warm_failed","reason":"indexing in progress"}`.
+a `degraded` error with code `index-running`, including requests for meaning only.
+`warm` replies `warm_failed` with the same `index-running` error.
 The daemon keeps its shared lock until its server stops. Reindex first tries
 the exclusive lock without blocking. If it is busy, reindex prints
 `waiting index.lock` once on stderr, holds an exclusive lock on
@@ -64,12 +134,13 @@ the child to exit. A standalone `omafind reindex` still waits for exclusive
 ownership as above.
 Words-only searches do not wait for server startup or embedding requests.
 When a meaning query needs a cold server, it starts warming in the background
-and replies immediately with `legs:["words"]` and
-`degraded:"the embedding server is starting"`, including requests for meaning
+and replies immediately with `legs:["words"]` and a `degraded` error with code
+`server-starting`, including requests for meaning
 only. This also applies while an explicit `warm` request is still starting the
 server, and after reindex releases its lock. A later identical query returns
-the requested legs once the server is warm. Startup failures still use
-`warm_failed.reason` for `warm`, or `results.degraded` for a query.
+the requested legs once the server is warm. A startup failure is a
+`server-start-failed` error with the cause and the `llama-server.log` path, in
+`warm_failed.error` for `warm` or in `results.degraded` for a query.
 After the `hello` reply, requests on one connection run concurrently. Search
 replies may arrive in any order; clients use `seq` to match them to requests.

@@ -103,18 +174,20 @@ Extracted HTML/docx/odt set `info.extracted:true`. `part` is `text`, `image`
 `speech` (a video soundtrack) or `audio`. `z` is null for words-only
 results. `weak` means score below half the top score. `total` counts qualified
 files before the limit; `weaker` counts weak items in the returned list.
-`degraded` is null or a reason string; embedding failures still return words.
+`degraded` is null or an error object (see Errors): `server-starting`,
+`index-running`, `server-start-failed` or `embedding-unavailable`. Embedding
+failures still return words.
 A `kinds:["code"]` search with no code index adds `notice:"no-code-index"` when no repository has
 Code turned on, or `notice:"code-index-pending"` when one has but the index is not built yet;
 `degraded` stays null.
 Timing fields are milliseconds.

-Proposed error replies are `{"t":"error","seq":7,"code":"no-index","reason":"No index exists. Run omafind reindex --root PATH."}` or
-`{"t":"error","seq":7,"code":"bad-request","reason":"Invalid search arguments"}`.
-An exception while handling a request replies
-`{"t":"error","seq":7,"reason":"no such table: meta"}` and leaves the
-connection open for the next request. `seq` echoes the request; `code` is
-optional for service errors.
+Error replies carry `seq` and the error fields, for example
+`{"t":"error","seq":7,"code":"no-index","title":"Nothing is indexed yet.","detail":"Open setup and start the first index."}`.
+Invalid search arguments reply `bad-request`. An exception while handling a
+request replies `internal` with the exception as the cause, such as
+`{"t":"error","seq":7,"code":"internal","title":"Something failed inside the omafind service.","detail":"No such table: meta.","fix":{"kind":"retry"}}`,
+and leaves the connection open for the next request. `seq` echoes the request.
 The CLI sends seq 1 with both legs and prints the complete results object for
 `--json`. It exits 0 for any result, 1 for no index or a service error, 2 for bad arguments, and
 3 for a silent socket.
@@ -124,8 +197,8 @@ Settings in the plugin's shell.json entry now include `roots` (default `[]`),
 `codeRoots` (absolute repository paths, default `[]`), and `imageBudget`
 (70, 140 or 280, default 140). Invalid paths are dropped; budgets are not coerced.
 `audio` (bool, default true) controls audio files and video soundtracks.
-With audio off, audio files have state `skipped` and detail `audio search is off`.
-Silent audio has detail `silent audio`. A failed soundtrack leaves frame vectors
+With audio off, audio files have state `skipped` and code `audio-off`.
+Silent audio has code `silent-audio`. A failed soundtrack leaves frame vectors
 in state `partial`, with a failure detail; it is retried on an explicit reindex.
 `info.thumb` and `thumb` contain a cached JPEG path in `thumbs/<volume-uuid>/`.
 There is no editor setting; openers read the Omarchy default editor.
@@ -141,7 +214,7 @@ After `hello`, the plugin may send:

 | t | Fields | Behavior |
 |---|---|---|
-| `preview` | `id`, `q` (string, default `""`) | Render the selected result on demand. Unknown IDs or missing online files reply with `error`, `code:"missing"`, `id` and `reason:"File is missing"`. |
+| `preview` | `id`, `q` (string, default `""`) | Render the selected result on demand. Unknown IDs or missing online files reply `error` with `id` and a `file-missing` error. |
 | `open` | `id`, `how:"open"\|"reveal"` (default `"open"`), optional `line` (int ≥ 1) | Open text and code at `line`, else at the preview jump, else at the chunk start; other kinds ignore `line`. `how:"reveal"` selects the file with detached `nautilus --select`. Offline and missing files run nothing. A bad `how` or `line` replies `error` with `for:"open"`, `code:"bad-request"`. |
 | `status` | none | Reply with current indexed-file and queue counts. |

@@ -149,8 +222,8 @@ After `hello`, the plugin may send:
 |---|---|---|
 | `preview` | `id`, `mode:"lines"\|"image"\|"bars"`, `lines:[{no,text,hit}]`, `jump`, `range:[first,last]\|null`, `image:path\|null`, `bars:[int]`, `opener`, `editor` (text/code only) | Text/code use a clamped ±8-line window. PDF/video render the selected page/second; online images use the source file, or a cached `magick` still at 1200 x 840 when Qt cannot decode the format (HEIC, AVIF, RAW); PDF pages render 1200 px on the long side. Audio has 64 RMS bars in 0..100. Unused arrays are empty. Offline items use mode `image` with their cached thumbnail or null. |
 | `opened` | `id`, `opener`, `at:string\|null` | Human command label and location: `mpv --start=872`/`14:32`, `omarchy-launch-browser`/`p. 37`, `nvim +212`/`L212`; images and reveals have null `at`. |
-| `open_failed` | `id`, `reason:"offline"\|"missing"` | The file cannot be opened; unknown IDs count as missing. |
-| `error` | `id`, `for:"open"`, `reason` | Opening raised an unexpected error. A failed preview replies `error` with `id` and no `for`. |
+| `open_failed` | `id`, `error` | The file cannot be opened: `drive-not-mounted` for a file on an unplugged drive, `file-missing` for a missing file or an unknown ID, `open-failed` with the cause when the opener fails to start. |
+| `error` | `id`, `for:"open"`, error fields | `bad-request` for invalid open arguments, `internal` for an unexpected exception. A failed preview replies `error` with `id` and no `for`. |
 | `status` | `files`, `roots`, `offline:[]`, `done`, `total` | Counts from all index stores, including code. Also pushed when changed, at most once every 0.5 seconds. |

 IDs resolve only against that connection's latest `results`; a `results` reply with a new `seq` clears
@@ -181,7 +254,7 @@ mtimes stay unchanged; the root count still follows current settings.
 {"t":"open","id":"b81e:812","how":"open"}
 {"t":"open","id":"b81e:812","how":"open","line":212}
 {"t":"opened","id":"b81e:812","opener":"mpv --start=872","at":"14:32"}
-{"t":"open_failed","id":"b81e:812","reason":"offline"}
+{"t":"open_failed","id":"b81e:812","error":{"code":"drive-not-mounted","title":"Photos2024 is not connected.","detail":"Connect it, then press Retry.","fix":{"kind":"retry"}}}
 {"t":"status"}
 {"t":"status","files":3880,"roots":4,"offline":[],"done":1204,"total":1209}
 ```
@@ -199,8 +272,9 @@ mtimes stay unchanged; the root count still follows current settings.
 | `fs_list` | `fs_list` | `path` absolute path or `~`/`~/...` |
 | `index_start` | `progress` | none; rereads current settings |
 | `index_progress` | `progress` | none; reads the stores and returns the latest snapshot without starting a run |
+| `retry_failed` | `retry_failed` | `code` a per-file failure code; the plugin sends `tool-missing` |

-All paths on the wire are absolute, except `excludes`, which are POSIX paths relative to their root. Requests may pass `"~"` or `"~/x"`; the daemon expands them and echoes the request string in `root`/`path` and the absolute path in `abs`. Every discovery `counts` object carries `text, pdf, image, video, audio, dirs` (zeros included). Every request below gets exactly one reply; failures reply `{"t":"error","for":"<request t>","code":"<code>","reason":"<sentence>"}` and never carry `seq` or `id` (Service.qml routes errors on `for` first).
+All paths on the wire are absolute, except `excludes`, which are POSIX paths relative to their root. Requests may pass `"~"` or `"~/x"`; the daemon expands them and echoes the request string in `root`/`path` and the absolute path in `abs`. Every discovery `counts` object carries `text, pdf, image, video, audio, dirs` (zeros included). Every request below gets exactly one reply; failures reply `{"t":"error","for":"<request t>",...}` with the error fields (see Errors) and never carry `seq` or `id` (Service.qml routes errors on `for` first).

 New messages are accepted only after `hello`, like `search`.

@@ -210,7 +284,7 @@ plugin: {"t":"runtime_install"}
 plugin: {"t":"runtime_pause"}
 daemon: {"t":"runtime_progress","state":"idle|running|paused|failed|done",
          "step":"build|download|null","file":"model|mmproj|null","done":512,"total":865,"unit":"MB",
-         "left_seconds":60|null,"reason":null|"<sentence>",
+         "left_seconds":60|null,"error":null|{error},
          "build":{"state":"wait|run|ok|failed","seconds":192|null,"tag":"b11461","backend":"Vulkan","gpu":"RTX 3060 12 GB"|null},
          "files":{"model":{"name":"embeddinggemma-2-Q8_0.gguf","state":"wait|run|verify|ok","done":310,"total":310},
                   "mmproj":{"name":"mmproj-embeddinggemma-2-Q8_0.gguf","state":"wait|run|verify|ok","done":202,"total":555}}}
@@ -219,6 +293,7 @@ daemon: {"t":"runtime_progress","state":"idle|running|paused|failed|done",
 - MB are decimal and rounded: 309,855,456 B is 310, 554,821,024 B is 555, `total` is `round(sum bytes / 1e6)` = 865. `done` sums both files.
 - `state:"done"` means the runtime is built and both digests verified. `files.*.state:"ok"` means sha256 verified (cached by size and mtime, so `runtime_status` hashes at most once per daemon start, in a thread). `build.seconds` is null when the runtime existed before this daemon started.
 - `runtime_install` while `running` is a no-op snapshot. While `paused` or `failed` it resumes.
+- `error` is null unless `state` is `failed`. Its code is `build-missing-packages`, `build-failed`, `build-no-scope`, `model-download-failed`, `model-verify-failed` or `internal`. Before it spawns the build, the daemon checks the build packages (`tools.BUILD_NEEDS`: `vulkan-headers`, `shaderc`, `gcc`, `git`, `uv`) and fails with `build-missing-packages` without starting it. The build writes its stdout and stderr to `<data>/cache/logs/build-runtime.log`, replaced at each run, and a build error carries that `log`. A failed build leaves `files.*.state` as it was.

 ```
 plugin: {"t":"discover_start"}                      // $HOME plus every non-system volume
@@ -246,7 +321,7 @@ daemon: {"t":"discover_counts","root":"/home/u","done":true,"seconds":1.4,"count
 ```
 - A fresh walk starts with `counts:{}`, `done:false`, `seconds:null`, and `reset:true`. Clients clear that root's previous counts, datasets, and child replies; a reused walk replays a snapshot without `reset`.
 - Sent about every 250 ms with the folders whose counts changed since the last batch. `counts` are rolled up: a folder counts every indexable file below it. `dirs` counts the rolled-up directories containing those files, including the folder itself; it never contributes to file totals. A folder the walk never reached has no entry; once `done` is true a missing folder has zero files.
-- The last batch has `done:true`, `seconds` rounded to 0.1, and `datasets`: media folders with 300 or more files of one kind (image, video or audio) of which at least 70% are machine-named; `named` is that share in percent. `repos` and `worktrees` are sorted lists of the absolute paths of the git repositories and linked worktrees the walk found. A done snapshot of a reused walk carries `datasets`, `repos` and `worktrees` too. A failed walk still ends with `done:true` and adds `error` (the last error line from fd or the OS reason). Failed walks are never cached, so the next discovery request retries. Folder and file names that cannot be encoded as UTF-8 are skipped.
+- The last batch has `done:true`, `seconds` rounded to 0.1, and `datasets`: media folders with 300 or more files of one kind (image, video or audio) of which at least 70% are machine-named; `named` is that share in percent. `repos` and `worktrees` are sorted lists of the absolute paths of the git repositories and linked worktrees the walk found. A done snapshot of a reused walk carries `datasets`, `repos` and `worktrees` too. A failed walk still ends with `done:true` and adds `error`, a `scan-failed` error whose cause is the last error line from fd or the OS reason. Failed walks are never cached, so the next discovery request retries. Folder and file names that cannot be encoded as UTF-8 are skipped.

 ```
 plugin: {"t":"discover_children","path":"/home/u/Pictures"}
@@ -257,14 +332,14 @@ daemon: {"t":"discover_children","path":"/home/u/Pictures","volume":"<uuid>","er
                  {"path":"/home/u/Pictures/2024","name":"2024","repo":false,"worktree":false,"hasChildren":true,
                   "counts":null,"rule":null,"evidence":null}]}
 ```
-- One level, same filters as `folders`, sorted by indexable files (descending), then by name. `counts` is null until the walk reaches the folder; the counts arrive later in `discover_counts`. Paths under a known root reuse its walk and volume UUID without probing the mount again, even after that walk is older than 300 s; only `discover_start` walks a root again. A path outside every known root starts a walk scoped to that path, even when its volume mount is higher up. `/`, `/proc`, `/sys`, `/dev`, `/run`, and paths below these pseudo-filesystem roots are refused with `bad-request`; a known mounted volume below `/run` can still be expanded. `volume` is the UUID of the volume holding `path`, or null. An unreadable folder replies `dirs:[]` with `error` set to the OS reason. A request still running when its connection sends `discover_stop` replies `{"t":"discover_stop"}` instead, and the plugin forgets every children request in flight when it stops discovery.
+- One level, same filters as `folders`, sorted by indexable files (descending), then by name. `counts` is null until the walk reaches the folder; the counts arrive later in `discover_counts`. Paths under a known root reuse its walk and volume UUID without probing the mount again, even after that walk is older than 300 s; only `discover_start` walks a root again. A path outside every known root starts a walk scoped to that path, even when its volume mount is higher up. `/`, `/proc`, `/sys`, `/dev`, `/run`, and paths below these pseudo-filesystem roots are refused with `bad-request`; a known mounted volume below `/run` can still be expanded. `volume` is the UUID of the volume holding `path`, or null. An unreadable folder replies `dirs:[]` with `error` set to a `scan-failed` error naming the OS reason. A request still running when its connection sends `discover_stop` replies `{"t":"discover_stop"}` instead, and the plugin forgets every children request in flight when it stops discovery.


 ```
 plugin: {"t":"fs_list","path":"~"}
 daemon: {"t":"fs_list","path":"~","abs":"/home/u","dirs":["Documents","Pictures"],"error":null}
 ```
-- Sorted case-insensitively, dot dirs and `rules.HEAVY_GLOBS` names left out, at most 500 names. `error` is `"missing"`, `"not-a-directory"` or `"denied"` (with `dirs:[]`) instead of an `error` reply.
+- Sorted case-insensitively, dot dirs and `rules.HEAVY_GLOBS` names left out, at most 500 names. A path that is missing, is not a folder or cannot be read gets `dirs:[]` and `error`, a `scan-failed` error naming that cause, instead of an `error` reply.

 ```
 plugin: {"t":"binds_get"}
@@ -277,16 +352,27 @@ plugin: {"t":"index_start"}
 daemon: {"t":"progress","running":true,"done":612,"queued":597,"volume":"<uuid>","device":"gpu","vram_gb":0.9,
          "kinds":{"text":{"done":734,"total":734},"pdf":{"done":31,"total":49,"pages":412},
                   "image":{"done":51,"total":420,"ocr":63},"video":{"done":0,"total":6},"audio":{"done":0,"total":0}},
-         "skipped":{"size-cap":2},"failed":{"encrypted-pdf":1},
-         "problems":[{"path":"/home/u/Documents/a.pdf","reason":"encrypted-pdf"}]}
+         "skipped":{"size-cap":2},"failed":{"encrypted-pdf":1,"tool-missing":12},
+         "problems":[{"path":"/home/u/Documents/a.pdf","code":"encrypted-pdf","detail":""}],
+         "tool_errors":[{"code":"tool-missing","title":"12 files need tesseract.",
+                         "detail":"They were indexed without text recognition. Install tesseract and they are indexed again.",
+                         "fix":{"kind":"install","packages":["tesseract"]}}]}
 ```
 - `index_progress` replies the same `progress` body and starts nothing, so a view can fill before the next broadcast.
 - Reply to `index_start` is a `progress` snapshot. Then the daemon broadcasts `progress` at most twice per second while the index job runs, and once more when it exits (`running:false`). `status` keeps working unchanged for the #4 footer.
-- When the child exits non-zero, the final `progress` includes `exit:<code>` (negative for termination by a signal). The daemon then broadcasts exactly one `error` with `for:"index_start"`, `code:"runtime-failed"`, and a `reason` naming the exit code and the absolute `<data>/index/reindex.log` path. These broadcasts report failure after the initial reply; they carry no `seq` or `id`. Successful completion omits `exit` and sends no error.
+- When the child exits non-zero, the final `progress` includes `exit:<code>` (negative for termination by a signal). The daemon then broadcasts exactly one `error` with `for:"index_start"` and code `index-exited`, whose detail names the exit code and whose `log` is the absolute `<data>/index/reindex.log` path. These broadcasts report failure after the initial reply; they carry no `seq` or `id`. Successful completion omits `exit` and sends no error.
 - `device` is `gpu`, `cpu` or null; `vram_gb` is a float or null (unknown is null, the client hides the token). `skipped` and `failed` omit zero keys. Secrets are never listed, so they are not counted in `skipped`. `problems` lists at most 50 failed files.
-- A file whose embedding the server rejects gets detail `embedding-failed`: state `failed`, or, for a `partial` file whose earlier pages are already indexed, state `partial` with that detail. The halted file stays searchable up to where it stopped and leaves the queue.
+- `problems` items are `{path, code, detail}`, and `failed` counts files by the same `code`. Per-file codes are kebab-case: `encrypted-pdf`, `timeout`, `extract-failed`, `embedding-failed`, `embedding-precision-fault`, `soundtrack-failed`, `audio-off`, `silent-audio`, `tool-missing`, `code-index-failed`. `detail` is the extractor's own message; for `tool-missing` it names the tool. Code-index failures are counted and listed like any other file.
+- `tool_errors` holds one `tool-missing` error per missing tool, each with an install fix for that tool's package. It is `[]` when no file waits on a tool.
+- A file whose embedding the server rejects gets code `embedding-failed`: state `failed`, or, for a `partial` file whose earlier pages are already indexed, state `partial` with that detail. The halted file stays searchable up to where it stopped and leaves the queue.
 - `kinds.image.ocr` counts ready images with a non-empty OCR text segment (`kind:"ocr"`); filename and parent-folder text in `name` segments does not count.
-- Error codes: `no-roots` (settings have no roots and no codeRoots), `bad-request`, `scan-failed`, `runtime-failed`, `binds-failed`.
+- Error codes on these `error` replies: `no-roots` (settings have no roots and no codeRoots), `bad-request`, `scan-failed`, `drive-not-mounted` (a drive scan whose drive is gone), `binds-failed`, `index-exited` and `internal`. Runtime job failures arrive in `runtime_progress.error`, not as `error` replies.
+
+```
+plugin: {"t":"retry_failed","code":"tool-missing"}
+daemon: {"t":"retry_failed","code":"tool-missing","count":12}
+```
+- Marks every file whose last failure has `code` as stale, so the running pass or the next one indexes it again. `count` is the number of files marked. The plugin sends it when an install fix on a `tool-missing` error succeeds.

 The daemon owns the runtime job: closing a view or disconnecting a client does
 not pause it. Build pause terminates the build process group; resume reruns the
@@ -314,7 +400,7 @@ name from lsblk. Offline mounts are null.
 {"t":"drive_decision","uuid":"6BFF-B220","choice":"scan"}
 {"t":"drive_decision","uuid":"6BFF-B220","choice":"ignore"}
 {"t":"reconcile","uuid":"6BFF-B220","label":"Photos2024","done":120,"total":900}
-{"t":"paused","reason":"disk","free_gb":1.4,"need_gb":2}
+{"t":"paused","error":{"code":"disk-low","title":"Indexing is paused.","detail":"Free some disk space and indexing resumes by itself."},"free_gb":1.4,"need_gb":2}
 {"t":"resumed"}
 ```

@@ -340,7 +426,7 @@ while a child runs are deferred and processed after it exits.
 {"t":"discover_start","volume":"6BFF-B220"}
 {"t":"discover_result","volume":"6BFF-B220","roots":[{"path":"/run/media/u/Photos2024","volume":"6BFF-B220"}],"folders":[]}
 {"t":"index_start","volume":"6BFF-B220"}
-{"t":"progress","running":true,"done":612,"queued":597,"volume":"6BFF-B220","volumes":{"6BFF-B220":{"label":"Photos2024","done":612,"total":1209}},"device":null,"vram_gb":null,"kinds":{"text":{"done":612,"total":1209},"pdf":{"done":0,"total":0,"pages":0},"image":{"done":0,"total":0,"ocr":0},"video":{"done":0,"total":0},"audio":{"done":0,"total":0}},"skipped":{},"failed":{},"problems":[]}
+{"t":"progress","running":true,"done":612,"queued":597,"volume":"6BFF-B220","volumes":{"6BFF-B220":{"label":"Photos2024","done":612,"total":1209}},"device":null,"vram_gb":null,"kinds":{"text":{"done":612,"total":1209},"pdf":{"done":0,"total":0,"pages":0},"image":{"done":0,"total":0,"ocr":0},"video":{"done":0,"total":0},"audio":{"done":0,"total":0}},"skipped":{},"failed":{},"problems":[],"tool_errors":[]}
 {"t":"status","files":3880,"roots":4,"offline":["Photos2024"],"done":1204,"total":1209}
 ```

@@ -367,9 +453,9 @@ and keep the same relative `dir`. Internal-volume `dir` stays absolute.
 Mount aliases in health.json rebase configured roots and absolute excludes at
 read time before DB mount metadata advances, including child settings reads.

-If `state.model` is not `ready`, every search uses `legs:["words"]` and
-`degraded:"embedding model failed verification"`, including meaning-only
-requests. Startup verifies
+If `state.model` is not `ready`, every search uses `legs:["words"]` and a
+`degraded` error with code `embedding-unavailable` and the cause "Embedding model
+failed verification", including meaning-only requests. Startup verifies
 both model sizes and digests, checks volume DBs with `PRAGMA quick_check`,
 quarantines corrupt stores as `<uuid>.sqlite.bad`, and reconciles online roots
 when recovery is needed. health.json records verification, recovery and rebuild
````

- [ ] **Step 2: Edit `docs/DESIGN.md`**

What changes: yellow covers a degraded state. Card tones go after the offline badge line, with `update-running` in the yellow list. An error toast with a fix stays until Retry or Dismiss. The Banner row becomes a wrapper and a new Error card row describes Retry (a retry or install fix, where the view has no control of its own), Install packages staying pressable while it waits, and "Dismiss" under the open toast. Step 1 labels, the error copy example as title plus detail, the four plugin-written codes, and the instruction strings from `lib/setup.js` `engineHint`.

```diff
diff --git a/docs/DESIGN.md b/docs/DESIGN.md
index df7e446..76ce9fa 100644
--- a/docs/DESIGN.md
+++ b/docs/DESIGN.md
@@ -35,7 +35,7 @@ The Folders step follows `docs/superpowers/specs/2026-10-14-setup-and-search-ref

 - omafind looks like the Omarchy shell. It reads the current theme, follows the user's font and corner rounding, and adds no palette of its own. The canvas is rendered in Catppuccin, which is one Omarchy theme.
 - Flat surfaces. A 2 px border, no shadow, no blur. Tone and borders separate parts.
-- The accent means "this is the selection or the match". Yellow means a hit word, an offline drive or a dataset proposal. Red means a failure. Green means done, kept or protected.
+- The accent means "this is the selection or the match". Yellow means a hit word, an offline drive, a dataset proposal or a degraded state. Red means a failure. Green means done, kept or protected.
 - Square corners by default, as Omarchy is. Corners follow Hyprland `decoration:rounding` (0 by default, 8 on the author's machine).
 - The overlay is summoned, never parked. It opens on an empty query and closes after Enter or Esc.
 - Facts, not prose. omafind computes every status, so it shows the computed values as key/value tokens and keeps sentences for instructions, errors with a fix, and titles.
@@ -93,6 +93,7 @@ Other values with no theme token, derived in QML from the roles above:
 - Caption chips on images and frames `rgba(17,17,27,.85)`: `Util.alpha(Color.background, 0.85)`. The player play button uses 0.78.
 - Hit wash behind a word `rgba(249,226,175,.18)`: `Util.alpha(Palette.yellow, 0.18)`, text in `Palette.yellow`.
 - Offline badge fill: `Palette.yellow` at 0.12. Done step fill: `Palette.green` at 0.16. Running step fill: accent at 0.12.
+- Error card wash: `Color.urgent` at 0.08 for a failure, `Palette.yellow` at 0.08 for a degraded or paused state (`server-starting`, `index-running`, `embedding-unavailable`, `disk-low`, `update-running`). The glyph takes the same color. `tone()` in `lib/errors.js` maps the code to the tone; views never pick it.
 - Rule tag borders: accent for repos, cyan for worktrees and yellow for datasets.
 - Rendered PDF page `#e6e9ef` with text `#4c4f69`, and its hit highlight `rgba(223,142,29,.35)`: these draw page content, not shell chrome. They stay fixed in every theme.
 - Placeholder image tints `#2c3a52`, `#3a3346`, `#2f3f3d`, `#403a33`, `#33364a`: mock photo content. The real thumbnail replaces them.
@@ -179,7 +180,7 @@ The easing is `cubic-bezier(0.33, 1, 0.68, 1)` unless a row says `ease` or `line
 | Preview cross-fade | 120 ms opacity. The media area rises 6 px over 120 ms (160 ms in). | M1, M2 |
 | Empty to results | 140 ms opacity, results delayed 30 ms | M1 |
 | Open | Overlay closes, then the opener window fades in over 250 ms | M2 |
-| Toast | 180 ms in from 12 px right and 12 px up, stays 2.8 s | M1, M2, M4 |
+| Toast | 180 ms in from 12 px right and 12 px up, stays 2.8 s. An error toast with a fix stays until Retry or Dismiss. | M1, M2, M4 |
 | Progress | 300 ms linear on width, 200 ms on color | M3, M4 |
 | Setup panel resize | 240 ms on width and height | M3 |
 | Setup step swap | Out 120 ms, in 160 ms after a 120 ms delay | M3 |
@@ -214,7 +215,8 @@ Each row names the class in `omafind.css` and the boards where it appears.
 | Why line | `.pv-why`, `.fx`, `.f`, `.k`, `.v` | See Why line below. | every search board |
 | Preview actions | `.pv-act`, `.btn-acc`, `.btn-sec` | Primary in accent fill with base text, "Show in folder" secondary. Offline: "Open" disabled and "Copy path". | every search board |
 | Footer | `.sp-f` | Result count left ("17 results · 3 weaker"), key hints right. With no query: indexing progress, watched folders, offline drives. | every search board |
-| Banner | `.ban`, `.act` | Yellow wash at 0.08, glyph, bold lead, "Retry" button right. | Degraded |
+| Banner | `.ban`, `.act` | A thin wrapper around `ErrorCard` for the fact-token form (the disk banner). Yellow wash at 0.08, glyph, bold lead, fact tokens. | Degraded |
+| Error card | `ErrorCard` (`.ban` anatomy) | Glyph, bold title, detail wrapped and capped at three lines, buttons right: "Install packages" (install fix), "Open log" (log), "Retry" (a retry or install fix, only where the view has no retry control of its own; step 1 uses its footer). An install fix adds `sudo pacman -S --needed <packages>` in mono with "Copy", and shows "Installing in the terminal" next to the still pressable "Install packages" while it waits for the packages. The open toast adds "Dismiss" under the card. Red wash for a failure, yellow for a degraded or paused state. The compact form (preview pane, open toast) drops the pacman line and caps the detail at two lines. Shows nothing when its error is null. | Degraded. Not drawn on the setup, preview and toast boards. |
 | Empty state | `.empty`, `.hints`, `.hint` | Headline, one sentence, prefix chips (`img:`, `pdf:`, `doc:`, `vid:`, `aud:`, `code:`) with the prefix in accent. | Empty, M1 |
 | Steps | `.steps`, `.step`, `.no`, `.dash` | 20 px number box, done in green wash, current in accent. | Setup to Indexing, M3 |
 | Lazy folder tree | `FolderTree`, `FolderTable`, `FolderRow` | Check, disclosure, path, repo or dataset tag, five kind counts, index size, time, and code toggle. One ListView shared by setup and the drive dialog. | Folders step, NewDrive |
@@ -291,7 +293,7 @@ Setup:
 | `Space` | Folder checkbox | Toggle the folder. |
 | `Esc` | Empty state | Close. |

-Setup buttons, by step: "Pause" and "Next: pick folders"; "Back" and "Start indexing"; "Close" and "Save shortcut and open search"; "Not this drive" and "Scan"; "Cancel" and "Index this drive". The boards define no other setup key (see Open questions).
+Setup buttons, by step: "Install", "Pause" while it runs, "Retry" after a failure or "Resume" when paused, then "Next: pick folders"; "Back" and "Start indexing"; "Close" and "Save shortcut and open search"; "Not this drive" and "Scan"; "Cancel" and "Index this drive". The Setup board shows only "Pause"; the other step 1 labels come from the error handling spec. The boards define no other setup key (see Open questions).

 ## Copy

@@ -301,7 +303,7 @@ Every string comes verbatim from the boards. A string the canvas lacks follows t
 - No em or en dashes in prose. Use a comma, a colon, a period or parentheses. A dash used as a placeholder glyph, a range inside a fact token (`L1–47`, `7:55–8:25`) or the separator inside a composed label is typography and stays. The middle dot in `Photos2024 · /2019/lisbon` and in meta lines is the separator.
 - Terse and technical. A label or subtitle can be a fragment. A banner, toast or error is a full sentence.
 - A control says what it does ("Open", "Show in folder", "Copy path", "Retry", "Scan", "Index this drive"). A state is one word or a fact ("ready", "offline", "new").
-- An error says what happened, why, and what to do next, in that order. Example: "Semantic search unavailable: the embedding server did not start (Vulkan device lost). Showing keyword matches." with a "Retry" button.
+- An error says what happened, why, and what to do next, in that order. The title says what happened. The detail says why, then what to do next, and names a control ("press Retry"), never a CLI command. Example: title "The embedding server did not start.", detail "It did not answer within 60 s. Showing keyword matches until it starts.", with a "Retry" button. The daemon writes error copy in `helper/omafindd/errors.py`; the plugin writes only `daemon-offline` and `unknown` in `lib/errors.js`, and `update-running` and `update-failed` in `lib/Update.js` (see `docs/ipc.md`, Errors).
 - Avoid seamless, leverage, robust, comprehensive, delve, showcase, vibrant, crucial, pivotal, streamline, empower, foster, testament, landscape, tapestry, journey, unlock and elevate.

 ### Facts, not prose
@@ -319,8 +321,8 @@ Keys the boards use that spec 7.4 does not list: `dataset`, `searchable`, `mount
 What stays a sentence:

 - Titles: "Set up omafind", "Pick the folders to search", "Indexing your files", "New drive found".
-- Instructions: "Type a description in any language. Start with a prefix to search one kind only." and "You can close this. The download keeps going."
-- Errors with a fix: "Photos2024 is not connected. Connect it to open this file."
+- Instructions: "Type a description in any language. Start with a prefix to search one kind only.", "Install builds the server (about 3 min) and downloads the model (865 MB)." and "You can close this. Installing keeps going."
+- Errors with a fix: "Photos2024 is not connected." with "Connect it, then press Retry."
 - Prompts: "Photos2024 (exFAT, 1.8 TB) is connected. Scan it for photos, videos and documents to search?"
 - Setup explanation: "omafind writes its own block in your Hyprland bindings and reloads Hyprland. Nothing else in your config changes."
 - Toasts: a short sentence, or a title plus fact tokens (`Opening <name>` with `opener` and `at`).
```

- [ ] **Step 3: Edit `README.md`**

What changes: the Install button. Status exit 1 and the `tools` row include missing tools and, while the runtime is missing, build packages. The startup log line. A Troubleshooting section before `## Threat model`: the log table, the build packages, and which commands stop before the build. `setup --json` with `build_missing`, and that missing build packages do not stop setup. Audio off as a code. Degraded during reindex.

````diff
diff --git a/README.md b/README.md
index 287f482..ebd90f1 100644
--- a/README.md
+++ b/README.md
@@ -17,7 +17,7 @@ bin/omafind setup
 bin/omafind build-runtime
 ```

-Setup creates `~/.local/share/omafind/venv`, copies the user unit into `~/.config/systemd/user/omafind.service`, enables it and waits for `hello`. Repeat setup to apply unit changes. Runtime building and model downloads start through `build-runtime` or the setup view’s Download button. The daemon owns setup jobs, so closing the overlay leaves them running; Pause stops a job and Resume continues it.
+Setup creates `~/.local/share/omafind/venv`, copies the user unit into `~/.config/systemd/user/omafind.service`, enables it and waits for `hello`. Repeat setup to apply unit changes. Runtime building and model downloads start through `build-runtime` or the setup view’s Install button. The daemon owns setup jobs, so closing the overlay leaves them running; Pause stops a job and Resume continues it.

 The Vulkan build needs `vulkan-headers` and `shaderc`. Prefer installing the remaining build tools with `sudo pacman -S cmake ninja spirv-headers`. The script can bootstrap private copies when those are missing. It runs in a memory-capped systemd user scope (12 GiB, no swap) when the user manager is available. It builds the pinned llama.cpp runtime, then downloads and verifies both pinned model files.

@@ -26,7 +26,7 @@ Run `bin/omafind status` for fact lines or `bin/omafind status --json` for JSON.
 | Exit | Meaning |
 |---|---|
 | 0 | Unit enabled and active, socket answers `hello` |
-| 1 | Unit not installed or not enabled |
+| 1 | A tool is missing (while the runtime is missing, build packages count too; stderr prints the `pacman` line), or the unit is not installed or not enabled |
 | 2 | Unit enabled but not active |
 | 3 | Unit active but socket silent |
 | 4 | Daemon answers, but the venv is `missing`, `stale` or `unknown` |
@@ -37,7 +37,7 @@ Run `bin/omafind status` for fact lines or `bin/omafind status --json` for JSON.
 |---|---|
 | `unit` | `{enabled, active}` |
 | `socket` | `{path, answers}` |
-| `tools` | `{missing: [tool]}` |
+| `tools` | `{missing: [package]}`: missing runtime tools, plus the build packages while the runtime binary is missing |
 | `venv` | `{path, state}`; `state` is `ready`, `stale` (does not match `helper/uv.lock`, from `uv sync --check`), `missing` or `unknown` (uv not found or the venv unreadable) |
 | `runtime` | `{path, present}` |
 | `model` | `{path, files, verified}`; `files` maps pinned filenames to presence booleans; `verified` is the last daemon verdict, false before a report exists |
@@ -53,7 +53,7 @@ and `problem <uuid> integrity rebuilt` when applicable.
 Unreadable or corrupt indexes retain a volume entry with zero counts until recovery rebuilds them.
 See [docs/ipc.md](docs/ipc.md) for the handshake.

-When the plugin code changes (a `git pull` in a dev checkout or a marketplace update), the plugin compares `bin/omafind fingerprint` with the `build` the daemon reports and reruns `bin/omafind setup` once, which syncs the venv and restarts the unit. A daemon that starts on a venv missing a dependency logs `omafindd cannot import <module>. Run bin/omafind setup.` to the unit journal and exits 1.
+When the plugin code changes (a `git pull` in a dev checkout or a marketplace update), the plugin compares `bin/omafind fingerprint` with the `build` the daemon reports and reruns `bin/omafind setup` once, which syncs the venv and restarts the unit. A daemon that starts on a venv missing a dependency logs `omafindd cannot import <module>. Run bin/omafind setup.` to the unit journal and to `~/.local/share/omafind/cache/logs/omafindd-start.log`, and exits 1. A socket bind failure is logged the same way.

 Settings live inline on the `radimsem.omafind` entry in `~/.config/omarchy/shell.json`. The plugin writes them through `updateEntryInline`; the daemon only reads them. Later issues add keys.

@@ -70,6 +70,25 @@ Settings live inline on the `radimsem.omafind` entry in `~/.config/omarchy/shell
 | `warmMinutes` | int, clamped to 0..60 | `5` |
 | `shortcut` | uppercase `MODS + KEY` (mods: SUPER, SHIFT, CTRL, ALT) or a lone `F1` to `F35` | `"SUPER + E"` |

+## Troubleshooting
+
+Setup and search show every failure as a card: what happened, why, and what to do next. A card with a log offers Open log. [docs/ipc.md](docs/ipc.md#errors) lists every code. The logs live under `~/.local/share/omafind`:
+
+| Log | Holds |
+|---|---|
+| `cache/logs/build-runtime.log` | Full output of the last runtime build (CMake, ninja and the compiler), replaced at each build |
+| `cache/logs/llama-server.log` | Output of the embedding server since its last start, replaced at each start. The API key reaches the server only through its environment, so it never appears here. |
+| `cache/logs/omafindd-start.log` | A fatal daemon startup error, such as a failed import or socket bind |
+| `index/reindex.log` | Output of the last indexing run the daemon started, replaced at each run |
+
+`build-missing-packages` means the runtime build needs an Arch package that is not installed. `build-runtime` and the Install button check for `vulkan-headers` (`/usr/include/vulkan/vulkan_core.h`), `shaderc` (`glslc`), `gcc` (`c++`), `git` and `uv` before the build starts. `setup` only names the missing ones, because it also runs when the daemon updates; `status` lists them under `tools` and exits 1. A build that still stops on a missing `vulkan/`, `spirv/` or `shaderc/` header reports the same code with that header's package. The card names the packages. Install packages runs `omarchy-pkg-add` in a floating terminal and retries the build once they are present. To install every package the check looks for from a terminal:
+
+```bash
+sudo pacman -S --needed vulkan-headers shaderc gcc git uv
+```
+
+Then press Retry or run `bin/omafind build-runtime`. Any other build error is `build-failed`, with the first error line as the cause; `build-runtime.log` has the full output.
+
 ## Threat model

 The index, snippets, OCR text and thumbnails are stored unencrypted inside the user's home.
@@ -117,7 +136,10 @@ The reference inputs `photo.jpg`, `screen.png` and `speech.wav` in `tests/fixtur
 Required tools: fd 10+, rg, magick, pdfinfo, pdftotext, pdftoppm, git, findmnt,
 ffmpeg, ffprobe and tesseract.
 `omafind setup` checks them before installing the daemon. Missing tools produce
-one `sudo pacman -S --needed ...` command.
+one `sudo pacman -S --needed ...` command. Missing build packages do not stop
+setup: while the runtime is missing, setup names them on stderr. With `--json`,
+setup prints `{"ok":true,"build_missing":[...]}` or `{"ok":false,"error":{...}}`
+as its last stdout line instead (see [Errors](docs/ipc.md#errors)).

 ```bash
 systemd-run --user --scope --quiet --collect -p MemoryMax=8G -p MemorySwapMax=0 -- bin/omafind reindex --root "$HOME/Documents"
@@ -172,8 +194,8 @@ OCR text is searchable without a vector. JPEG thumbnails live in `thumbs/<uuid>/
 Video and audio results open through `mpv --start=<seconds>`.

 Audio uses 30 s windows with a 25 s hop, skips RMS at or below 0.003, and keeps
-tails with at least 2 s of new audio. `audio:false` skips audio files with detail
-`audio search is off` and indexes videos as frames only. Silent files are skipped.
+tails with at least 2 s of new audio. `audio:false` skips audio files with code
+`audio-off` and indexes videos as frames only. Silent files are skipped.
 Video frames are extracted and committed in passes of at most 16 frames before
 the soundtrack starts. Long audio is extracted and committed in batches of at most
 16 windows, keeping decoded payload memory bounded as well as streaming PCM one
@@ -186,8 +208,8 @@ Indexes live in `$XDG_DATA_HOME/omafind/index/<uuid>.sqlite` (default
 mount point (the home mount for its UUID, otherwise the shortest target).
 A CLI reindex holds `index.lock`; completed PDF windows commit atomically,
 and the journal retries interrupted batches. The daemon reloads changed indexes
-before searching. During reindex it serves words-only results with
-`degraded:"indexing in progress"` and rejects `warm` with the same reason.
+before searching. During reindex it serves words-only results with a
+`degraded` error of code `index-running` and rejects `warm` with the same error.
 A reindex that finds the daemon's server warm prints `waiting index.lock`; the daemon
 stops that server within half a second.
 Incremental reindexes the daemon starts itself, after a file change or a drive
````

- [ ] **Step 4: Check the copy**

```bash
grep -nP "[\x{2013}\x{2014}]" docs/ipc.md docs/DESIGN.md README.md
git diff -U0 docs/ipc.md docs/DESIGN.md README.md | grep -nP "^\+.*[\x{2013}\x{2014}]"
git diff --check
```

Expected: the first command shows only hits that were there before (DESIGN.md fact-token ranges such as `L1–47` and `7:55 – 8:25`, and the Open questions lines). The second prints nothing. `git diff --check` prints nothing. Also confirm no added line contains "!", and that no `reason` field is left on a daemon message:

```bash
grep -n '"reason"' docs/ipc.md
```

Expected: no hits. (`reason` may still appear as a word in prose, as in "the OS reason".)

- [ ] **Step 5: Run the full checks**

```bash
uv run --project helper pytest -q
node --test "tests/js/*.test.mjs"
uv run --project helper ruff check helper tests bin/omafind scripts evals
scripts/qmllint.sh
git diff --check
```

Expected: `1039 passed, 1 deselected`, `pass 260` and `fail 0`, `All checks passed!`, no qmllint output, and no `git diff --check` output. This task changes only Markdown, so any failure comes from an earlier task; stop and fix it there.

- [ ] **Step 6: Commit**

```bash
git status
git diff --staged
git add docs/ipc.md docs/DESIGN.md README.md
git diff --staged --stat
git commit -S -m "docs: describe the error object, codes and logs"
```

Stage only these three files. Never stage `.superpowers/` or `.pytest_cache`.
