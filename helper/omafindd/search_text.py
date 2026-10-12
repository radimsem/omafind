import re
import unicodedata


def normalized(text: str) -> str:
    result = []
    for character in unicodedata.normalize("NFKC", text):
        code = ord(character)
        if code == 0x200B:
            result.append(" ")
        elif (
            code in (0xAD, 0x61C, 0xFEFF, 0x640, 0x670)
            or 0x200C <= code <= 0x200F
            or 0x202A <= code <= 0x202E
            or 0x2060 <= code <= 0x2064
            or 0x2066 <= code <= 0x2069
            or 0x64B <= code <= 0x65F
        ):
            continue
        elif code in (0x622, 0x623, 0x625, 0x671):
            result.append("ا")
        else:
            result.append(character)
    return "".join(result)


def terms(text: str) -> list[str]:
    words, word = [], []
    for character in normalized(text).lower():
        category = unicodedata.category(character)
        if category[0] in "LNM" or category == "Co":
            word.append(character)
        elif word:
            words.append("".join(word))
            word = []
    if word:
        words.append("".join(word))
    return list(dict.fromkeys(words))


def inflects(word: str) -> bool:
    return any(0x600 <= ord(c) <= 0x6FF or 0x900 <= ord(c) <= 0xDFF for c in word)


def pattern(word: str) -> str:
    return '"' + word.replace('"', '""') + '"' + ("*" if inflects(word) else "")


def snippet_parts(marked: str) -> list[dict]:
    return [
        {"t": part.strip("«»"), "m": part.startswith("«")}
        for part in re.split(r"(«[^»]*»)", marked)
        if part
    ]
