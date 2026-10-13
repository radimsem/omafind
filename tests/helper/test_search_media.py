import pytest
from fakes.embedder import FakeEmbedder


@pytest.mark.parametrize("segment_kind,file_kind,part,loc", [
    ("frame", "video", "frame", 9.5), ("audio", "video", "speech", 25),
    ("audio", "audio", "audio", 25), ("image", "image", "image", None),
])
async def test_media_best_segment_and_prefix(tmp_path, segment_kind, file_kind, part, loc):
    from omafindd.extractors import Segment
    from omafindd.search import Searcher
    from omafindd.store import Store

    store = Store(tmp_path / "index/v.sqlite", volume="v", mount=tmp_path)
    fake = FakeEmbedder()
    query, other = await fake.embed_documents(["needle", "unrelated"])
    try:
        for index in range(26):
            kind = file_kind if index == 0 else "image"
            file = store.db.execute(
                "INSERT INTO files(path,kind,size,mtime,inode,device) VALUES(?,?,0,0,0,0)",
                (f"file{index}", kind),
            ).lastrowid
            segments = [Segment(segment_kind, "audio" if segment_kind == "audio" else "image",
                                loc=loc)] if index == 0 else [Segment("image", "image")]
            if index == 0 and file_kind == "video":
                segments.insert(0, Segment("frame", "image", loc=0.5))
            vectors = [other] * (len(segments) - 1) + [query if index == 0 else other]
            store.write(file, segments, vectors, state="done", info={})
        item = (await Searcher([store], fake).search("needle"))["items"][0]
        assert (item["part"], item["loc"]) == (part, loc)
        videos = (await Searcher([store], fake).search("vid: needle"))["items"]
        assert all(item["kind"] == "video" for item in videos)
        assert len(videos) == (1 if file_kind == "video" else 0)
    finally:
        store.close()
