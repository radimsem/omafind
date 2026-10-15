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
    "index_running": (),
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


def test_build_failure_keeps_an_unknown_missing_header_as_build_failed(tmp_path):
    log = tmp_path / "build-runtime.log"
    log.write_text("x.cpp:1:10: fatal error: foo/bar.h: No such file or directory\n")
    error = errors.build_failure(log, 1)
    assert error.code == "build-failed"
    assert error.detail.startswith("x.cpp:1:10: fatal error: foo/bar.h: No such file or directory.")
