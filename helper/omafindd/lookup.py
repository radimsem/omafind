import re
from collections.abc import Sequence

DEFINERS = set(
    "def func fn fun function class struct enum protocol interface trait type typealias actor "
    "extension impl module namespace object record macro const let var val union mod sub "
    "@interface @implementation @protocol #define function*".split()
)
USERS = set(
    "return await yield throw new else case print echo assert not and or in is do go defer try "
    "catch if while for typeof delete raise import from".split()
)
COMMENT_STARTS = ("//", "#", "/*", "*", "--", '"""', "'''", "<!--", ";")


def identifier(query: str) -> list[str] | None:
    name = query.strip().removesuffix("()")
    pattern = r"[A-Za-z_$][A-Za-z0-9_$]*(?:(?:\.|::|->|#)[A-Za-z_$][A-Za-z0-9_$]*)*"
    if not re.fullmatch(pattern, name):
        return None
    camel = any(c.isupper() for c in name[1:]) and any(c.islower() for c in name)
    if not camel and not any(c in "_.:#$" or c.isdigit() for c in name):
        return None
    return [word for word in re.split(r"[^\w]|_", name.lower()) if word]


def phrase(words: Sequence[str]) -> str:
    return '"' + " ".join(words) + '"'


def defines_something(word: str) -> bool:
    return word in DEFINERS - {"let", "var", "const", "val"}


def definition(name: str, text: str, first: int = 1) -> tuple[int, int] | None:
    best = None
    pattern = re.compile(r"(?<![\w$])" + re.escape(name) + r"(?![\w$])", re.IGNORECASE)
    for offset, line in enumerate(text.replace("\r\n", "\n").split("\n")):
        for match in pattern.finditer(line):
            before, after = line[:match.start()].strip(), line[match.end():].strip()
            previous = before.split()[-1] if before else ""
            strength = 0
            if previous in DEFINERS or before.startswith("func (") and before.endswith(")"):
                strength = 2
            elif before.startswith(("- (", "+ (")):
                strength = 2 if not after or after.startswith((":", "{", ";")) else 0
            elif (after.startswith("(") and before and previous not in USERS
                  and not any(c in "=(,.!?" for c in before) and "->" not in before
                  and (before[-1].isalnum() or before[-1] in "*&>_]")):
                strength = 1 if line.strip().endswith(";") else 2
            if strength > (best[1] if best else 0):
                best = first + offset, strength
            if strength == 2:
                return best
    return best


def has(word: str, line: str) -> bool:
    for match in re.finditer(re.escape(word), line, re.IGNORECASE):
        start = match.start()
        if start == 0 or not line[start - 1].isalnum() or line[start].isupper():
            return True
    return False


def first_line(words: Sequence[str], text: str, first: int = 1) -> int | None:
    words = [word.lower() for word in words if len(word) >= 2]
    first_code = first_any = None
    for offset, line in enumerate(text.replace("\r\n", "\n").split("\n")):
        if not any(has(word, line) for word in words):
            continue
        trimmed = line.strip()
        if any(defines_something(word) for word in trimmed.split()[:4]):
            return first + offset
        if first_code is None and not trimmed.startswith(COMMENT_STARTS):
            first_code = offset
        if first_any is None:
            first_any = offset
    found = first_code if first_code is not None else first_any
    return first + found if found is not None else None
