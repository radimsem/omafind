from fakes.embedder import FakeEmbedder
from support.media import InlinePool, command


async def test_screenshot_ocr_is_fts_only_and_thumbnail_is_saved(tmp_path, monkeypatch):
    from omafindd import jobs
    from omafindd.crawler import crawl
    from omafindd.search import Searcher
    from omafindd.store import Store

    path = tmp_path / "screenshot-text.png"
    command("magick", "-size", "1200x160", "xc:white", "-fill", "black", "-font",
            "Liberation-Sans", "-pointsize", "42", "-annotate", "+20+90",
            "externally-managed-environment", str(path))
    monkeypatch.setattr(jobs, "ProcessPoolExecutor", InlinePool)
    store = Store(tmp_path / "index/v.sqlite", volume="v", mount=tmp_path)
    try:
        crawl(store, [{"path": str(tmp_path)}])
        await jobs.Jobs(store, FakeEmbedder(), journal=tmp_path / "journal").drain()
        row = store.db.execute("SELECT body,vec FROM fts JOIN segments s ON s.id=fts.rowid "
                               "WHERE s.kind='ocr'").fetchone()
        assert "externally-managed-environment" in row["body"]
        assert row["vec"] is None
        result = await Searcher([store], None).search("externally managed environment")
        item = result["items"][0]
        assert item["part"] == "ocr" and item["loc"] is None
        from pathlib import Path
        thumb = Path(item["thumb"])
        assert thumb.parent == tmp_path / "thumbs/v"
        assert thumb.exists() and thumb.stat().st_mode & 0o777 == 0o600
    finally:
        store.close()


def test_non_screenshot_does_not_run_tesseract(tmp_path, monkeypatch):
    import subprocess

    from omafindd.extractors import extract_image

    path = tmp_path / "IMG_0001.png"
    command("magick", "-size", "400x300", "xc:white", str(path))
    run = subprocess.run

    def checked(argv, **kwargs):
        assert argv[0] != "tesseract"
        return run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", checked)
    assert extract_image(path).ocr_text == ""


async def test_ocr_match_keeps_ocr_part_when_image_also_matches(tmp_path):
    from omafindd.extractors import Segment
    from omafindd.search import Searcher
    from omafindd.store import Store

    store = Store(tmp_path / "index/v.sqlite", volume="v", mount=tmp_path)
    fake = FakeEmbedder()
    needle, other = await fake.embed_documents(["needle", "unrelated"])
    try:
        for index in range(26):
            file = store.db.execute(
                "INSERT INTO files(path,kind,size,mtime,inode,device) "
                "VALUES(?,'image',0,0,0,0)", (f"image{index}",),
            ).lastrowid
            store.write(file, [Segment("image", "image")],
                        [needle if index == 0 else other], state="done", info={},
                        ocr_text="needle" if index == 0 else "")
        item = (await Searcher([store], fake).search("needle"))["items"][0]
        assert item["part"] == "ocr"
        assert item["hits"] == ["needle"]
    finally:
        store.close()


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
