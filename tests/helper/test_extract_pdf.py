import pytest
from support.corpus import copy_corpus, pdf


def test_pdf_text_page(tmp_path):
    from omafindd.extractors import extract_pdf

    root = copy_corpus(tmp_path / "corpus")
    result = extract_pdf(root / "invoice.pdf")
    assert result.state == "done"
    assert result.segments[0].kind == "page"
    assert result.segments[0].loc == 1
    assert "invoice 4412" in result.segments[0].text


def test_pdf_image_is_sized_to_280_tokens(tmp_path):
    from omafindd.extractors import ImagePart, extract_pdf

    root = copy_corpus(tmp_path / "corpus")
    result = extract_pdf(root / "scan.pdf")
    segment = result.segments[0]
    assert segment.kind == "page_image"
    assert isinstance(segment.image, ImagePart)
    assert segment.image.width % 48 == segment.image.height % 48 == 0
    assert segment.image.width * segment.image.height <= 280 * 2304
    assert segment.image.data.startswith(b"\x89PNG")


def test_long_pdf_reads_first_30_then_rest(tmp_path):
    from omafindd.extractors import extract_pdf

    path = pdf(tmp_path / "long.pdf", [(f"page {n} research " * 25) for n in range(60)])
    first = extract_pdf(path)
    assert first.state == "partial"
    assert [s.loc for s in first.segments] == list(range(1, 31))
    second = extract_pdf(path, start=31)
    assert second.state == "done"
    assert [s.loc for s in second.segments] == list(range(31, 61))


@pytest.mark.parametrize("pages", [33, 40, 50])
def test_pdf_at_most_50_pages_finishes_first_extraction(tmp_path, pages):
    from omafindd.extractors import extract_pdf

    path = pdf(tmp_path / "short.pdf", ["lunar eclipse research " * 25] * pages)
    result = extract_pdf(path)
    assert result.state == "done"
    assert result.info["read_to"] == pages
    assert [segment.loc for segment in result.segments] == list(range(1, pages + 1))


def test_encrypted_pdf_fails_with_detail(tmp_path):
    from omafindd.extractors import ExtractionError, extract_pdf

    root = copy_corpus(tmp_path / "corpus")
    with pytest.raises(ExtractionError, match="encrypted-pdf"):
        extract_pdf(root / "locked.pdf")


@pytest.mark.parametrize("name,needle", [("garden.docx", "orchid"), ("travel.odt", "railway")])
def test_office_zip_text(tmp_path, name, needle):
    from omafindd.extractors import extract_text

    root = copy_corpus(tmp_path / "corpus")
    result = extract_text(root / name)
    assert needle in result.segments[0].text.lower()
    assert result.info["extracted"] is True


def test_extreme_image_aspect_ratio_stays_in_budget():
    from omafindd.extractors import target_size

    for w, h in [(1, 100000), (100000, 1), (724, 1024)]:
        width, height = target_size(w, h, 280)
        assert width % 48 == height % 48 == 0
        assert 0 < width * height <= 280 * 2304


def test_pdf_image_windows_and_page_cap(tmp_path, monkeypatch):
    from omafindd import extractors

    renders = []

    def command(argv, *, text=True):
        if argv[0] == "pdfinfo":
            return "Pages: 5002\n"
        if argv[0] == "pdftotext":
            return "\f" * (int(argv[argv.index("-l") + 1]) - int(argv[argv.index("-f") + 1]) + 1)
        if argv[0] == "pdftoppm":
            renders.append(int(argv[argv.index("-f") + 1]))
            return ""
        return "48 48" if text else b"png"

    monkeypatch.setattr(extractors, "_pdf_command", command)
    first = extractors.extract_pdf(tmp_path / "fixture.pdf")
    second = extractors.extract_pdf(tmp_path / "fixture.pdf", start=31)
    last = extractors.extract_pdf(tmp_path / "fixture.pdf", start=4991)
    assert (len(first.segments), first.info["read_to"], first.state) == (30, 30, "partial")
    assert (len(second.segments), second.info["read_to"], second.state) == (32, 62, "partial")
    assert (len(last.segments), last.info["read_to"], last.state) == (10, 5000, "done")
    assert renders == list(range(1, 63)) + list(range(4991, 5001))


@pytest.mark.parametrize("tool", ["pdfinfo", "pdftotext", "pdftoppm", "magick"])
def test_pdf_tools_have_timeout_and_report_timeout(monkeypatch, tool):
    import subprocess

    from omafindd.extractors import ExtractionError, _pdf_command

    def run(argv, **kwargs):
        assert kwargs["timeout"] == 60
        raise subprocess.TimeoutExpired(argv, 60)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ExtractionError, match="^timeout$"):
        _pdf_command([tool, "fixture"])


def test_long_pdf_page_becomes_several_segments_on_one_page(tmp_path):
    from omafindd.extractors import TOKEN_CAP, estimated_tokens, extract
    from support.corpus import pdf

    path = tmp_path / "long.pdf"
    pdf(path, ["word " * 1500])
    result = extract(path, "pdf", 1)
    pages = [segment for segment in result.segments if segment.kind == "page"]
    assert len(pages) >= 3
    assert {(segment.loc, segment.loc_end) for segment in pages} == {(1, 1)}
    assert all(estimated_tokens(segment.text) <= TOKEN_CAP for segment in pages)
