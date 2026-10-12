import bisect
import html
import math
import re
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree


class ExtractionError(Exception):
    pass


@dataclass(frozen=True)
class ImagePart:
    data: bytes
    width: int
    height: int


@dataclass(frozen=True)
class Segment:
    kind: str
    modality: str
    text: str = ""
    loc: int | None = None
    loc_end: int | None = None
    image: ImagePart | None = None


@dataclass
class Extracted:
    segments: list[Segment]
    info: dict = field(default_factory=dict)
    state: str = "done"


def chunks(text: str) -> list[Segment]:
    newlines = [i for i, character in enumerate(text) if character == "\n"]
    result = []
    start = 0
    while start < len(text) and len(result) < 5000:
        end = min(start + 1800, len(text))
        if end < len(text):
            space = next((i for i in range(end - 1, start + 900, -1) if text[i].isspace()), None)
            if space is not None:
                end = space
        left, right = start, end
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        if left < right:
            result.append(
                Segment(
                    "chunk",
                    "text",
                    text[left:right],
                    bisect.bisect_left(newlines, left) + 1,
                    bisect.bisect_left(newlines, right) + 1,
                )
            )
        if end == len(text):
            break
        next_start = max(start + 1, end - 200)
        while next_start < end and not text[next_start].isspace():
            next_start += 1
        start = next_start
    return result


def plain_text_html(text: str) -> str:
    for pattern in (
        r"(?is)<script\b.*?</script\s*>",
        r"(?is)<style\b.*?</style\s*>",
        r"(?s)<!--.*?-->",
        r"(?is)<head\b.*?</head\s*>",
    ):
        text = re.sub(pattern, " ", text)
    text = re.sub(r"(?i)<(br|/p|/div|/li|/h[1-6]|/tr|/section|/article)\b[^>]*>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def extract_text(path: Path) -> Extracted:
    extension = path.suffix.lower()
    if extension in (".docx", ".odt"):
        member = "word/document.xml" if extension == ".docx" else "content.xml"
        try:
            with zipfile.ZipFile(path) as archive:
                tree = ElementTree.fromstring(archive.read(member))
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as error:
            raise ExtractionError("unreadable Office file") from error
        paragraphs = [
            "".join(node.itertext())
            for node in tree.iter()
            if node.tag.rsplit("}", 1)[-1] in ("p", "h")
        ]
        text = "\n".join(paragraphs)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
        if extension == ".html":
            text = plain_text_html(text)
    info = {"extracted": True} if extension in (".html", ".docx", ".odt") else {}
    return Extracted(chunks(text), info)


def target_size(width: int, height: int, budget: int) -> tuple[int, int]:
    factor = math.sqrt(budget * 2304 / (width * height))
    w, h = int(factor * width / 48) * 48, int(factor * height / 48) * 48
    if w == 0:
        w, h = 48, min(max(48, height // width * 48), budget * 48)
    elif h == 0:
        h, w = 48, min(max(48, width // height * 48), budget * 48)
    return w, h


def _pdf_command(argv, *, text=True):
    try:
        result = subprocess.run(argv, capture_output=True, text=text, timeout=60)
    except subprocess.TimeoutExpired as error:
        raise ExtractionError("timeout") from error
    if result.returncode:
        detail = result.stderr if text else result.stderr.decode(errors="replace")
        raise ExtractionError(
            "encrypted-pdf" if "Incorrect password" in detail else f"{argv[0]} failed"
        )
    return result.stdout


def extract_pdf(path: Path, start: int = 1) -> Extracted:
    info = _pdf_command(["pdfinfo", str(path)])
    match = re.search(r"(?m)^Pages:\s+(\d+)", info)
    if match is None:
        raise ExtractionError("pdfinfo returned no page count")
    pages = int(match[1])
    end = min(pages, 5000, (30 if start == 1 else start + 31) if pages > 50 else pages)
    if start > end:
        return Extracted([], {"pages": pages, "read_to": end})
    text = _pdf_command(
        ["pdftotext", "-f", str(start), "-l", str(end), "-enc", "UTF-8", str(path), "-"]
    )
    texts = text.split("\f")
    if texts and not texts[-1].strip():
        texts.pop()
    if len(texts) != end - start + 1:
        raise ExtractionError("pdftotext returned an unexpected page count")
    segments = []
    with tempfile.TemporaryDirectory(prefix="omafind-pdf-") as directory:
        for page, body in enumerate(texts, start):
            body = body.strip()
            if len(body) >= 200:
                segments.append(Segment("page", "text", body, loc=page))
                continue
            prefix = Path(directory) / "page"
            _pdf_command(
                [
                    "pdftoppm",
                    "-f",
                    str(page),
                    "-l",
                    str(page),
                    "-scale-to",
                    "1024",
                    "-singlefile",
                    "-png",
                    str(path),
                    str(prefix),
                ]
            )
            image = prefix.with_suffix(".png")
            width, height = map(
                int, _pdf_command(["magick", "identify", "-format", "%w %h", str(image)]).split()
            )
            width, height = target_size(width, height, 280)
            data = _pdf_command(
                [
                    "magick",
                    str(image),
                    "-filter",
                    "Catrom",
                    "-resize",
                    f"{width}x{height}!",
                    "png:-",
                ],
                text=False,
            )
            segments.append(
                Segment("page_image", "image", body, loc=page, image=ImagePart(data, width, height))
            )
    return Extracted(
        segments, {"pages": pages, "read_to": end}, "partial" if end < min(pages, 5000) else "done"
    )


def extract(path: Path, kind: str, start: int = 1) -> Extracted:
    return extract_pdf(path, start) if kind == "pdf" else extract_text(path)
