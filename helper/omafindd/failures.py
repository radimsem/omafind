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


def decode(value: str | None) -> tuple[str, str]:
    """`(code, detail)` from a stored value.

    Any other text becomes `extract-failed` with it as detail.
    """
    if not value:
        return "extract-failed", ""
    if value in LEGACY:
        return LEGACY[value], ""
    code, _, detail = value.partition(": ")
    return (code, detail) if code in CODES else ("extract-failed", value)
