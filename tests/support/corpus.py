import shutil
import subprocess
import textwrap
import zlib
from pathlib import Path

CORPUS = Path(__file__).resolve().parents[1] / "fixtures/corpus"


def copy_corpus(destination):
    return Path(shutil.copytree(CORPUS, destination))


def pdf(path, texts, image=None):
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pages = []
    for text in texts:
        page_id = len(objects) + 1
        pages.append(page_id)
        if image is None:
            lines = textwrap.wrap(text, 85)
            content = b"BT /F1 10 Tf 36 760 Td 14 TL "
            for line in lines:
                escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                content += f"({escaped}) Tj T* ".encode()
            content += b"ET"
            resources = b"/Font << /F1 3 0 R >>"
        else:
            content = b"q 500 0 0 700 36 36 cm /Im0 Do Q"
            resources = f"/XObject << /Im0 {page_id + 2} 0 R >>".encode()
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            + b"/Resources << "
            + resources
            + b" >> /Contents "
            + f"{page_id + 1} 0 R >>".encode()
        )
        objects.append(
            b"<< /Length "
            + str(len(content)).encode()
            + b" >>\nstream\n"
            + content
            + b"\nendstream"
        )
        if image is not None:
            data = zlib.compress(image)
            objects.append(
                b"<< /Type /XObject /Subtype /Image /Width 16 /Height 16 "
                b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode "
                + f"/Length {len(data)} >>\nstream\n".encode()
                + data
                + b"\nendstream"
            )
    objects[1] = (
        f"<< /Type /Pages /Count {len(pages)} /Kids ["
        + " ".join(f"{page} 0 R" for page in pages)
        + "] >>"
    ).encode()
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    )
    path.write_bytes(output)
    return path


def image_pdf(path):
    image = subprocess.run(
        ["magick", "-size", "16x16", "xc:steelblue", "-depth", "8", "rgb:-"],
        check=True,
        capture_output=True,
    ).stdout
    return pdf(path, [""], image=image)
