def test_chunk_size_overlap_and_line_locations():
    from omafindd.extractors import chunks

    text = "\n".join(f"line {n:04d} " + "x" * 80 for n in range(100))
    result = chunks(text)
    assert len(result) > 1
    offsets = []
    for segment in result:
        offset = text.find(segment.text)
        offsets.append(offset)
        assert len(segment.text) <= 1800
        assert segment.loc == text[:offset].count("\n") + 1
        assert segment.loc_end == text[: offset + len(segment.text)].count("\n") + 1
    assert 0 < offsets[0] + len(result[0].text) - offsets[1] <= 200


def test_chunk_cap():
    from omafindd.extractors import chunks

    assert len(chunks("x " * 4_100_000)) == 5000


def test_html_excludes_script_and_decodes_entities(tmp_path):
    from omafindd.extractors import extract_text

    path = tmp_path / "a.html"
    path.write_text("<head>omit</head><p>Hello &amp; &#x41;</p><script>omit</script><p>world</p>")
    result = extract_text(path)
    assert result.segments[0].text == "Hello & A\nworld"
    assert result.info == {"extracted": True}


def test_empty_text_has_no_chunks():
    from omafindd.extractors import chunks

    assert chunks("") == []
