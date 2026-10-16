import struct

import pytest
from support.media import command


def test_target_size_portrait_budgets():
    from omafindd.extractors import target_size

    assert target_size(1080, 1920, 140) == (384, 720)
    assert target_size(1080, 1920, 280) == (576, 1056)


def test_screenshot_predicate():
    from omafindd.rules import screenshot_like

    assert screenshot_like("screenshot-2026-04-20_10-47-06.png", 4000, 3000)
    assert screenshot_like("SCREENSHOT.png", 4000, 3000)
    assert screenshot_like("desktop.png", 1920, 1080)
    assert not screenshot_like("IMG_0001.jpg", 4000, 3000)


def test_exif_orientation_resize_and_thumbnail(tmp_path):
    from omafindd.extractors import extract_image

    path = tmp_path / "IMG_0001.jpg"
    command("magick", "-size", "4000x3000", "xc:red", str(path))
    # Minimal EXIF APP1 with TIFF orientation 6, independent of metadata tools.
    tiff = b"II" + struct.pack("<HIH", 42, 8, 1)
    tiff += struct.pack("<HHIHHI", 274, 3, 1, 6, 0, 0)
    app1 = b"Exif\0\0" + tiff
    jpeg = path.read_bytes()
    path.write_bytes(jpeg[:2] + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + jpeg[2:])
    result = extract_image(path)
    segment = result.segments[0]
    assert (segment.kind, segment.modality, segment.loc) == ("image", "image", None)
    assert (segment.image.width, segment.image.height) == (480, 624)
    assert result.info["width"] == 3000 and result.info["height"] == 4000
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(result.thumbnail)
    assert command("magick", "identify", "-format", "%w %h", str(thumb)) == b"450 600"


def test_thumbnail_is_at_most_600_and_quality_90(tmp_path):
    from omafindd.extractors import _thumbnail

    source = tmp_path / "big.png"
    command("magick", "-size", "1600x1200", "xc:gray", str(source))
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(_thumbnail(str(source)))
    assert command("magick", "identify", "-format", "%w %h %Q", str(thumb)) == b"600 450 90"


def test_thumbnail_does_not_enlarge_small_images(tmp_path):
    from omafindd.extractors import _thumbnail

    source = tmp_path / "small.png"
    command("magick", "-size", "80x60", "xc:gray", str(source))
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(_thumbnail(str(source)))
    assert command("magick", "identify", "-format", "%w %h", str(thumb)) == b"80 60"


@pytest.mark.parametrize("budget,expected", [(70, (432, 336)), (280, (912, 672))])
def test_image_budget(tmp_path, budget, expected):
    from omafindd.extractors import extract_image

    path = tmp_path / "photo.png"
    command("magick", "-size", "400x300", "xc:red", str(path))
    image = extract_image(path, image_budget=budget).segments[0].image
    assert (image.width, image.height) == expected


def test_screenshots_override_image_budget(tmp_path):
    from omafindd.extractors import extract_image

    path = tmp_path / "SCREENSHOT.png"
    command("magick", "-size", "400x300", "xc:white", str(path))
    image = extract_image(path, image_budget=70).segments[0].image
    assert (image.width, image.height) == (912, 672)


def test_animated_image_uses_first_frame(tmp_path):
    from omafindd.extractors import extract_image

    path = tmp_path / "animation.gif"
    command("magick", "-size", "100x50", "xc:red", "xc:blue", str(path))
    result = extract_image(path)
    assert len(result.segments) == 1
    assert (result.info["width"], result.info["height"]) == (100, 50)
