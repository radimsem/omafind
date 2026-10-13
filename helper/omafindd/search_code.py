import asyncio
import json
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from .code import CodeStore, classify_code, read
from .lookup import COMMENT_STARTS, definition, has, identifier
from .rules import SECRET_GLOBS
from .search_text import snippet_parts


def open_line(name: str, words: Sequence[str], text: str, first: int = 1) -> int | None:
    name = re.split(r"\.|::|->|#", name.strip().removesuffix("()"))[-1]
    pattern = (r"\b(?:def|class|fn|func|function|const|let|var|type|struct|interface)\s+"
               + re.escape(name) + r"(?:$|[^A-Za-z0-9_$])")
    rows = text.replace("\r\n", "\n").split("\n")
    code = "\n".join(line if not line.strip().startswith(COMMENT_STARTS) else "" for line in rows)
    result = subprocess.run(["rg", "-n", "-m1", "-i", "-e", pattern], input=code,
                            capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise OSError(result.stderr.strip())
    if result.stdout:
        offset, line = result.stdout.split(":", 1)
        found = definition(name, line, first=first + int(offset) - 1)
        if found:
            return found[0]
    # Keep offsets while excluding comments and partial matches inside longer words.
    code = "\n".join(line if not line.strip().startswith(COMMENT_STARTS) and
                     any(has(word, line) for word in words if len(word) >= 2) else ""
                     for line in rows)
    if not words:
        return None
    args = ["rg", "-n", "-m1", "-F", "-i"]
    for word in words:
        args.extend(["-e", word])
    result = subprocess.run(args, input=code, capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise OSError(result.stderr.strip())
    if result.stdout:
        return first + int(result.stdout.split(":", 1)[0]) - 1
    return None


async def words_leg(roots: Sequence[Path], words: Sequence[str], files: dict) -> dict:
    if not roots or not words:
        return {}
    args = ["rg", "--json", "-F", "-i"]
    for word in words:
        args.extend(["-e", word])
    for glob in SECRET_GLOBS:
        args.extend(["-g", f"!{glob}"])
    args.extend(["--", *(str(root) for root in roots)])
    hits = {}
    with tempfile.TemporaryFile() as errors, subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=errors,
    ) as process:
        try:
            for line in process.stdout:
                event = json.loads(line)
                if event["type"] != "match":
                    continue
                data = event["data"]
                if "text" not in data["path"]:
                    continue
                path = os.path.abspath(data["path"]["text"])
                if path not in files:
                    continue
                entry = hits.setdefault(path, {"words": set(), "line": data["line_number"],
                                               "snippet": data["lines"].get("text", "").strip()})
                for submatch in data["submatches"]:
                    value = submatch["match"].get("text", "").lower()
                    entry["words"].update(word for word in words if word.lower() == value)
            if process.wait() not in (0, 1):
                errors.seek(0)
                raise OSError(errors.read().decode(errors="replace").strip())
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    return hits


def _marked(text: str, words: Sequence[str]) -> list[dict]:
    if words:
        pattern = "|".join(re.escape(word) for word in words)
        text = re.sub(pattern, lambda match: "«" + match[0] + "»", text, flags=re.IGNORECASE)
    return snippet_parts(text)


async def search_code(searcher, q: str, *, roots: Sequence[Path], directory: Path | None,
                      legs, limit, seq, begun) -> dict:
    from .search import fused_score, is_lookup, meaning, query_terms

    named = identifier(q)
    words = [q.strip().removesuffix("()")] if named else query_terms(q)
    path = directory / "code.sqlite" if directory is not None else None
    available = bool(roots and path is not None and path.is_file())
    reply = {"t": "results", "seq": seq, "legs": list(legs), "ms": {}, "total": 0,
             "weaker": 0, "degraded": None, "items": []}
    embed_ms = words_ms = scan_ms = 0
    if q and available:
        store = CodeStore.open_existing(path.absolute(), Path("/"))
        try:
            store.db.execute("BEGIN")
            files = {str(store.mount / row["path"]): row for row in
                     store.db.execute("SELECT * FROM files WHERE state='done'")
                     if any((store.mount / row["path"]).is_relative_to(root) for root in roots)}
            async def timed_words():
                word_begun = time.monotonic()
                hits = await words_leg(roots, words if "words" in legs else [], files)
                return hits, (time.monotonic() - word_begun) * 1000

            query_result, (hits, words_ms) = await asyncio.gather(
                searcher._query(q, "meaning" in legs), timed_words(),
            )
            vector, reply["degraded"], embed_ms = query_result
            scan_begun = time.monotonic()
            best = {}
            if vector is not None:
                selected = {file["id"] for file in files.values()}
                rows = [row for row in
                        store.db.execute("SELECT * FROM segments WHERE vec IS NOT NULL")
                        if row["file"] in selected]
                if rows:
                    matrix = np.stack([np.frombuffer(row["vec"], dtype=np.float16) for row in rows])
                    zs = meaning(matrix.astype(np.float32) @ vector,
                                 [row["modality"] for row in rows])
                    for row, z in zip(rows, zs, strict=True):
                        if row["file"] not in best or z > best[row["file"]][0]:
                            best[row["file"]] = float(z), row
            scan_ms = (time.monotonic() - scan_begun) * 1000
            scored = []
            for filename, file in files.items():
                hit = hits.get(filename)
                semantic = best.get(file["id"])
                if not hit and not (semantic and semantic[0] >= 2):
                    continue
                live = Path(filename)
                if not classify_code(live) or live.is_symlink():
                    continue
                try:
                    pieces = read(live)
                except (OSError, ValueError, TypeError):
                    continue
                if hit and live.suffix.lower() == ".ipynb":
                    # rg sees notebook JSON; only authored cell sources count as words.
                    matching = [piece for piece in pieces if any(
                        word.lower() in piece.text.lower() for word in words)]
                    if not matching:
                        hit = None
                    else:
                        hit = {"words": {word for word in words if any(
                            word.lower() in piece.text.lower() for piece in matching)},
                            "line": matching[0].first, "snippet": matching[0].text.splitlines()[0]}
                coverage = len(hit["words"]) / len(words) if hit and words else 0
                z = semantic[0] if semantic else 0
                if z < 2 and coverage < 0.5:
                    continue
                rows = store.db.execute("SELECT * FROM segments WHERE file=? ORDER BY loc,id",
                                        (file["id"],)).fetchall()
                segment = semantic[1] if semantic else None
                if hit:
                    segment = min(rows, key=lambda row: (
                        0 if row["loc"] <= hit["line"] <= row["loc_end"] else
                        min(abs(row["loc"] - hit["line"]), abs(row["loc_end"] - hit["line"])),
                        row["loc"],
                    )) if rows else segment
                if segment is None:
                    continue
                piece = next((piece for piece in pieces if piece.first == segment["loc"]
                              and piece.last == segment["loc_end"]), None)
                jump = open_line(q, named or words, piece.text, piece.first) if piece else None
                if live.suffix.lower() == ".ipynb":
                    jump = None
                score = fused_score(z, coverage, lookup=named is not None or is_lookup(q),
                                    hinted=False)
                item = {"id": f"code:{file['id']}:{segment['id']}", "kind": "code",
                        "path": filename, "name": live.name, "dir": str(live.parent),
                        "volume": "code", "label": "code", "offline": False,
                        "loc": segment["loc"], "loc_end": segment["loc_end"], "open_line": jump,
                        "leg": "meaning + words" if z >= 2 and hit else
                        "meaning" if z >= 2 else "words", "part": "text",
                        "z": z if semantic else None, "score": score, "weak": False,
                        "hits": [word for word in words if hit and word in hit["words"]],
                        "snippet": _marked(
                            hit["snippet"] if hit else segment["excerpt"] or "", words),
                        "thumb": None, "mtime": file["mtime"], "size": file["size"],
                        "info": json.loads(file["info"] or "{}")}
                scored.append(item)
            scored.sort(key=lambda item: (-item["score"], item["path"]))
            reply["total"] = len(scored)
            reply["items"] = scored[:limit]
            for item in reply["items"]:
                item["weak"] = item["score"] < scored[0]["score"] * 0.5
            reply["weaker"] = sum(item["weak"] for item in reply["items"])
        finally:
            store.close()
    reply["ms"] = {"embed": round(embed_ms, 3), "scan": round(scan_ms, 3),
                   "words": round(words_ms, 3),
                   "total": round((time.monotonic() - begun) * 1000, 3)}
    return reply
