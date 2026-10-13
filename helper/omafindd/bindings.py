import json
import re
from dataclasses import dataclass
from pathlib import Path

from .settings import valid_shortcut

MODIFIERS = {"SHIFT": 1, "CTRL": 4, "ALT": 8, "SUPER": 64}
COMMAND = "omarchy-shell shell toggle radimsem.omafind '{\"view\":\"search\"}'"


@dataclass(frozen=True)
class Bind:
    mods: int
    key: str
    description: str
    ours: bool = False


def parse_key(chord):
    if not valid_shortcut(chord):
        raise ValueError(f"Invalid Hyprland shortcut: {chord}")
    parts = [part.strip() for part in chord.split("+")]
    return sum(MODIFIERS[part] for part in parts[:-1]), parts[-1]


def parse_binds(text) -> list[Bind]:
    if text.lstrip().startswith("["):
        values = json.loads(text)
        return [Bind(value["modmask"], value["key"], value.get("description", ""),
                     value.get("description") == "omafind") for value in values
                if not value.get("submap")]
    binds = []
    owned = False
    quoted = r'"(?:\\.|[^"\\])*"'
    for line in text.splitlines():
        if line.strip() == "-- omafind-shortcut-start":
            owned = True
        elif line.strip() == "-- omafind-shortcut-end":
            owned = False
        elif match := re.match(rf"\s*o\.bind\(\s*({quoted})\s*,\s*({quoted}|nil)", line):
            chord = json.loads(match[1])
            description = "" if match[2] == "nil" else json.loads(match[2])
            try:
                mods, key = parse_key(chord)
            except ValueError:
                continue
            binds.append(Bind(mods, key, description, owned and description == "omafind"))
    return binds


def matching(chord, binds):
    mods, key = parse_key(chord)
    return [bind for bind in binds if bind.mods & ~(2 | 16) == mods and bind.key.upper() == key]


def check(chord, binds) -> str:
    holders = matching(chord, binds)
    if any(not bind.ours for bind in holders):
        return "conflict"
    return "ours" if holders else "free"


def first_free(binds):
    return next((chord for chord in ("SUPER + E", "SUPER + D", "SUPER + U")
                 if check(chord, binds) == "free"), None)


def render_block(chord):
    parse_key(chord)
    return ("-- omafind-shortcut-start\n"
            f'o.bind({json.dumps(chord)}, "omafind", {json.dumps(COMMAND)})\n'
            "-- omafind-shortcut-end\n")


def _span(contents, start, end):
    left, right = contents.find(start), contents.find(end)
    if left == right == -1:
        return None
    if left == -1 or right < left or contents.count(start) != 1 or contents.count(end) != 1:
        raise ValueError("Invalid omafind markers")
    return left, right + len(end)


def _write(path, contents, changed):
    if contents == changed:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(changed)
    return True


def write_block(path, chord="SUPER + E") -> bool:
    path = Path(path).expanduser().resolve()
    contents = path.read_bytes() if path.exists() else b""
    block = render_block(chord).encode()
    span = _span(contents, b"-- omafind-shortcut-start", b"-- omafind-shortcut-end")
    if span is None:
        separator = b"\n" if contents and not contents.endswith(b"\n") else b""
        changed = contents + separator + block
    else:
        left, right = span
        changed = contents[:left] + block.rstrip(b"\n") + contents[right:]
    return _write(path, contents, changed)


def remove_block(path) -> bool:
    path = Path(path).expanduser().resolve()
    if not path.exists():
        return False
    contents = path.read_bytes()
    span = _span(contents, b"-- omafind-shortcut-start", b"-- omafind-shortcut-end")
    if span is None:
        return False
    left, right = span
    if contents[right:right + 2] == b"\r\n":
        right += 2
    elif contents[right:right + 1] == b"\n":
        right += 1
    return _write(path, contents, contents[:left] + contents[right:])


def write_menu_row(path) -> bool:
    path = Path(path).expanduser().resolve()
    contents = path.read_bytes() if path.exists() else b"{}\n"
    row = json.dumps({"icon": "\uf002", "label": "Find files", "action": COMMAND},
                     separators=(",", ":"), ensure_ascii=False)
    block = (f'\n// omafind-menu-start\n  "find": {row},\n// omafind-menu-end\n').encode()
    span = _span(contents, b"\n// omafind-menu-start", b"// omafind-menu-end\n")
    if span is None:
        opening = next((match.start(1) for match in re.finditer(
            rb"/\*.*?\*/|//[^\r\n]*|(\{)", contents, re.DOTALL
        ) if match[1]), None)
        if opening is None:
            raise ValueError("Omarchy menu must contain an object")
        changed = contents[:opening + 1] + block + contents[opening + 1:]
    else:
        left, right = span
        changed = contents[:left] + block + contents[right:]
    return _write(path, contents, changed)


def remove_menu_row(path) -> bool:
    path = Path(path).expanduser().resolve()
    if not path.exists():
        return False
    contents = path.read_bytes()
    span = _span(contents, b"\n// omafind-menu-start", b"// omafind-menu-end\n")
    if span is None:
        return False
    left, right = span
    return _write(path, contents, contents[:left] + contents[right:])
