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
