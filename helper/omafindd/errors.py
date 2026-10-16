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


def index_running() -> UserError:
    return UserError(
        "index-running", "Indexing is running.", "Showing keyword matches until it finishes."
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
    detail = (
        f"It could not be indexed without {what}. Install {package} and it is indexed again."
        if count == 1
        else (
            f"They could not be indexed without {what}. "
            f"Install {package} and they are indexed again."
        )
    )
    return UserError(
        "tool-missing",
        f"{files} {tool}.",
        detail,
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
