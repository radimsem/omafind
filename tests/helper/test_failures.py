import pytest
from omafindd import failures


def test_encode_keeps_the_code_and_one_short_line():
    assert failures.encode("timeout") == "timeout"
    assert failures.encode("tool-missing", "tesseract") == "tool-missing: tesseract"
    assert failures.encode("extract-failed", "\n  first\nsecond") == "extract-failed: first"
    assert failures.encode("extract-failed", "x" * 300) == "extract-failed: " + "x" * 200


@pytest.mark.parametrize("value,expected", [
    (None, ("extract-failed", "")),
    ("encrypted-pdf", ("encrypted-pdf", "")),
    ("tool-missing: tesseract", ("tool-missing", "tesseract")),
    ("embedding-failed: HTTP 500: too large", ("embedding-failed", "HTTP 500: too large")),
    ("embedding precision fault", ("embedding-precision-fault", "")),
    ("soundtrack embedding failed", ("soundtrack-failed", "")),
    ("audio search is off", ("audio-off", "")),
    ("silent audio", ("silent-audio", "")),
    ("HTTP 500: too large", ("extract-failed", "HTTP 500: too large")),
])
def test_decode_reads_codes_and_older_sentences(value, expected):
    assert failures.decode(value) == expected


def test_every_code_round_trips():
    for code in failures.CODES:
        assert failures.decode(failures.encode(code, "why")) == (code, "why")
