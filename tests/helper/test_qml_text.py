import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QML = sorted([*ROOT.glob("*.qml"), *(ROOT / "ui").glob("*.qml")])
TEXT = re.compile(r"^\s*(?:delegate:\s*|component \w+:\s*)?Text\s*\{", re.MULTILINE)


def test_static_text_goes_through_label():
    owners = {path.relative_to(ROOT).as_posix(): len(TEXT.findall(path.read_text()))
              for path in QML}
    assert {name: n for name, n in owners.items() if n} == {
        "ui/Label.qml": 1, "ui/QueryRow.qml": 1,
    }


def test_small_sizes_only_in_bold_uppercase_headers():
    users = [path.relative_to(ROOT).as_posix() for path in QML
             if re.search(r"Style\.font\.caption|Tokens\.tiny", path.read_text())]
    assert users == ["ui/SectionHeader.qml"]


def test_letter_spacing_is_whole_pixels():
    lines = [line.strip() for path in QML for line in path.read_text().splitlines()
             if "letterSpacing" in line]
    assert lines
    assert all("Math.round(" in line for line in lines)
