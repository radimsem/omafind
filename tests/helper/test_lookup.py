import pytest


@pytest.mark.parametrize("query,words", [
    ("retry_with_backoff", ["retry", "with", "backoff"]),
    ("RetryPolicy.run", ["retrypolicy", "run"]),
    ("camelCase()", ["camelcase"]), ("retry", None), ("Renamer", None),
    ("retry with backoff", None), ("foo::bar", ["foo", "bar"]),
])
def test_identifier(query, words):
    from omafindd.lookup import identifier, phrase

    assert identifier(query) == words
    if words:
        assert phrase(words) == '"' + " ".join(words) + '"'


def test_definition_and_first_line():
    from omafindd.lookup import defines_something, definition, first_line

    text = "# retry_with_backoff\n" + "\n" * 6 + "def retry_with_backoff():\n    pass"
    assert definition("retry_with_backoff", text, first=1) == (8, 2)
    assert first_line(["retry"], text, first=1) == 8
    assert defines_something("def") and not defines_something("const")
    assert definition("retry", "return retry()", first=10) is None
    assert definition("retry", "static void retry();", first=10) == (10, 1)
    assert definition("retry", "static void retry() {", first=10) == (10, 2)
    assert first_line(["retry"], "# retry\nretryWithBackoff()", first=4) == 5
    assert first_line(["try"], "retry()", first=1) is None


def test_open_line_is_bounded_to_stretch():
    from omafindd.search_code import open_line

    text = "# retry_with_backoff\n" + "\n" * 6 + "def retry_with_backoff():\n    pass"
    assert open_line("retry_with_backoff", ["retry", "backoff"], text, first=1) == 8
    assert open_line("retry", ["retry"], "# retry\n    retry()", first=40) == 41
    assert open_line("missing", ["missing"], text, first=1) is None


def test_open_line_excludes_comments_and_handles_dollar_names():
    from omafindd.search_code import open_line

    text = "# def retry_with_backoff():\ncall(retry_with_backoff)\ndef retry_with_backoff(): pass"
    assert open_line("retry_with_backoff", ["retry"], text) == 3
    assert open_line("retry", ["retry"], "# retry") is None
    assert open_line("$retry", ["retry"], "invoke($retry)\nconst $retry = 1") == 2
