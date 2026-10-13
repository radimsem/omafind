import json
import os
import re
import time
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from .embedder import EmbeddingError
from .embedding import Embedder, validated
from .search_text import normalized, pattern, snippet_parts, terms
from .store import Store

PREFIXES = {
    "img": "image",
    "pdf": "pdf",
    "vid": "video",
    "aud": "audio",
    "doc": "text",
    "code": "code",
}
KIND_WORDS = {
    "image": "image",
    "images": "image",
    "photo": "image",
    "photos": "image",
    "picture": "image",
    "pictures": "image",
    "screenshot": "image",
    "screenshots": "image",
    "pdf": "pdf",
    "pdfs": "pdf",
    "paper": "pdf",
    "papers": "pdf",
    "document": "text",
    "documents": "text",
    "note": "text",
    "notes": "text",
    "video": "video",
    "videos": "video",
    "clip": "video",
    "movie": "video",
    "audio": "audio",
    "song": "audio",
    "podcast": "audio",
    "voice": "audio",
    "sound": "audio",
    "ছবি": "image",
    "পিডিএফ": "pdf",
    "নোট": "text",
    "ভিডিও": "video",
    "অডিও": "audio",
    "صورة": "image",
    "صور": "image",
    "مستند": "text",
    "فيديو": "video",
    "صوت": "audio",
    "تسجيل": "audio",
}
STOPWORDS = set(
    "a an the of in on at to for with and or my me that this these those from about "
    "where what which who when is was are were be it its some any find show file files "
    "photo photos picture image images screenshot screenshots video videos pdf "
    "document documents recording এবং ও এই সেই একটি আমার থেকে জন্য সাথে মধ্যে কোথায় "
    "কোন কী কি যে ছবি স্ক্রিনশট ভিডিও ফাইল পিডিএফ في من على الى عن مع هذا هذه ذلك التي "
    "الذي اين ما صورة صور لقطة شاشة فيديو ملف مستند".split()
)


def query_terms(text):
    return [word for word in terms(text) if len(word) >= 2 and word not in STOPWORDS]


def is_lookup(text: str) -> bool:
    words = query_terms(text)
    return bool(re.search(r'"[^"\n]+"', text)) or bool(
        words
        and all(
            any(c.isdigit() for c in word) and (any(c.isalpha() for c in word) or len(word) >= 4)
            for word in words
        )
    )


def fused_score(z, coverage, *, lookup, hinted):
    wm, ww = (0.5, 4) if lookup else (1, 2)
    return wm * max(z, 0) + ww * coverage**1.5 + int(hinted)


def meaning(
    scores: np.ndarray, modalities: Sequence[str], scale=None, *, groups=None
) -> np.ndarray:
    if len(scores) == 0:
        return np.empty(0)
    scores = scores.astype(np.float64)
    scale = np.ones(len(scores), dtype=bool) if scale is None else np.asarray(scale, dtype=bool)
    if not scale.any():
        scale[:] = True
    if groups is None:
        modalities = np.asarray(modalities)
        groups = [modalities == modality for modality in np.unique(modalities)]
    global_mean = scores[scale].mean()
    centered = scores.copy()
    for group in groups:
        sample = group & scale
        average = scores[sample].mean() if sample.sum() >= 20 else global_mean
        centered[group] -= average
    deviation = max(float(centered[scale].std()), 0.02)
    return (centered - centered[scale].mean()) / deviation


class Searcher:
    def __init__(self, stores: Sequence[Store], embedder: Embedder | None, *, start=None,
                 code_directory: Path | None = None, code_roots: Sequence[Path] = ()):
        self.stores = [store for store in stores if store.path.name != "code.sqlite"]
        self.embedder = embedder
        self.code_directory, self.code_roots = code_directory, code_roots
        self.start = start
        self._signatures = None
        self.matrix = np.empty((0, 768), dtype=np.float32)
        self.columns = {
            name: np.empty(0, dtype=dtype)
            for name, dtype in {
                "volume": "U1", "id": np.int64, "file": np.int64,
                "modality": "U1", "loc": np.float64, "loc_end": np.float64,
                "kind": "U1", "file_kind": "U1", "scale": bool,
                "file_code": np.int64,
            }.items()
        }
        self._loaded = {}
        self._volume_codes = {}
        self._modality_groups = []

    def reload(self):
        signatures = [
            (
                store.volume,
                id(store.db),
                store.db.execute("PRAGMA data_version").fetchone()[0],
                store.db.total_changes,
            )
            for store in self.stores
        ]
        if signatures == self._signatures:
            return
        loaded = {}
        for store in self.stores:
            count, last = store.db.execute(
                "SELECT count(*),coalesce(max(id),0) FROM segments WHERE vec IS NOT NULL"
            ).fetchone()
            generation = store.db.execute(
                "SELECT value FROM meta WHERE key='segments_generation'"
            ).fetchone()
            loaded[store.volume, id(store.db)] = (
                count, last, int(generation[0]) if generation else 0
            )
        full = loaded.keys() != self._loaded.keys() or any(
            count < self._loaded[key][0]
            or last < self._loaded[key][1]
            or generation != self._loaded[key][2]
            for key, (count, last, generation) in loaded.items()
            if key in self._loaded
        )
        columns = {name: [] for name in self.columns}
        if full:
            self.matrix = np.empty((0, 768), dtype=np.float32)
            self._volume_codes = {store.volume: index for index, store in enumerate(self.stores)}
        count = sum(
            values[0] if full else values[0] - self._loaded[key][0]
            for key, values in loaded.items()
        )
        matrix = np.empty((count, 768), dtype=np.float32)
        offset = 0
        for store in self.stores:
            key = store.volume, id(store.db)
            if not full and loaded[key] == self._loaded[key]:
                continue
            last = 0 if full else self._loaded[key][1]
            for row in store.db.execute(
                "SELECT s.id,s.file,s.modality,s.loc,s.loc_end,s.kind,s.vec,f.kind AS file_kind,"
                "NOT(f.kind='pdf' AND coalesce(json_extract(f.info,'$.pages'),0)>50 "
                "AND coalesce(s.loc,0)>30) AS scale FROM segments s JOIN files f ON f.id=s.file "
                "WHERE s.vec IS NOT NULL AND s.id>? ORDER BY s.id", (last,)
            ):
                if len(row["vec"]) != 768 * 2:
                    continue
                vector = np.frombuffer(row["vec"], dtype=np.float16)
                if vector.shape != (768,) or not np.isfinite(vector).all():
                    continue
                for name in columns:
                    value = store.volume if name == "volume" else (
                        self._volume_codes[store.volume] << 40 | row["file"]
                        if name == "file_code" else row[name]
                    )
                    columns[name].append(value)
                matrix[offset] = vector
                offset += 1
        # Host: 500k×768 scans took 750 ms converting float16 blocks, 45 ms resident float32.
        if full or offset:
            matrix = matrix[:offset]
            self.matrix = matrix if full else np.concatenate((self.matrix, matrix))
            for name, values in columns.items():
                dtype = str if self.columns[name].dtype.kind == "U" else self.columns[name].dtype
                column = np.asarray(values, dtype=dtype)
                self.columns[name] = (
                    column if full else np.concatenate((self.columns[name], column))
                )
            modalities = self.columns["modality"]
            self._modality_groups = [
                modalities == modality for modality in np.unique(modalities)
            ]
        self._loaded = loaded
        self._signatures = signatures

    async def _words(self, words, kinds):
        begun = time.monotonic()
        keyword, coverage = {}, {}
        if words and kinds != []:
            matches = []
            for store in self.stores:
                sql = (
                    "SELECT s.file,s.id,s.kind,s.loc,s.loc_end,f.kind AS file_kind,"
                    "bm25(fts,3.0,1.0) AS rank "
                    "FROM fts JOIN segments s ON s.id=fts.rowid JOIN files f ON f.id=s.file "
                    "WHERE fts MATCH ?"
                )
                args = [" OR ".join(map(pattern, words))]
                if kinds is not None:
                    sql += " AND f.kind IN (" + ",".join("?" for _ in kinds) + ")"
                    args.extend(kinds)
                local = {}
                for row in store.db.execute(sql + " ORDER BY rank", args):
                    local.setdefault(row["file"], dict(row))
                    if len(local) == 100:
                        break
                matches.extend((row["rank"], store.volume, row) for row in local.values())
            for _, volume, row in sorted(
                matches, key=lambda entry: (entry[0], entry[1], entry[2]["id"])
            ):
                key = volume, row["file"]
                if key not in keyword and len(keyword) < 100:
                    keyword[key] = row
            for store in self.stores:
                ids = [file for volume, file in keyword if volume == store.volume]
                if not ids:
                    continue
                placeholders = ",".join("?" for _ in ids)
                for word in words:
                    for row in store.db.execute(
                        "SELECT DISTINCT s.file FROM fts JOIN segments s ON s.id=fts.rowid "
                        f"WHERE fts MATCH ? AND s.file IN ({placeholders})",
                        [pattern(word), *ids],
                    ):
                        key = store.volume, row[0]
                        coverage[key] = coverage.get(key, 0) + 1 / len(words)
        return keyword, coverage, (time.monotonic() - begun) * 1000

    async def _query(self, text, enabled):
        begun = time.monotonic()
        if not enabled:
            return None, None, 0
        if self.embedder is None:
            return None, "embedding model unavailable", 0
        try:
            await (self.start or self.embedder.start)("text")
            vector = validated(await self.embedder.embed_query(text)).astype(np.float32)
            return vector, None, (time.monotonic() - begun) * 1000
        except (EmbeddingError, OSError, ValueError) as error:
            return None, str(error), (time.monotonic() - begun) * 1000

    async def search(self, q: str, *, legs=("words", "meaning"), limit=40, seq=1,
                     kinds=None) -> dict:
        begun = time.monotonic()
        prefix = re.match(r"^\s*(img|pdf|vid|aud|doc|code):", q, re.IGNORECASE)
        if prefix:
            kind, q = PREFIXES[prefix[1].lower()], q[prefix.end() :].strip()
            kinds = [kind] if kinds is None or kind in kinds else []
        q = normalized(q).strip()
        code = None
        if kinds is not None and "code" in kinds:
            from .search_code import search_code

            code = await search_code(self, q, roots=self.code_roots, directory=self.code_directory,
                                     legs=legs, limit=limit, seq=seq, begun=begun)
            kinds = [kind for kind in kinds if kind != "code"]
            if not kinds:
                return code
        if not self.stores and kinds != [] and code is None:
            raise FileNotFoundError("No index exists. Run omafind reindex --root PATH.")
        query_result = await self._query(q, bool(q) and "meaning" in legs and kinds != []
                                         and bool(self.stores))
        opened = []
        try:
            for store in self.stores:
                store.db.execute("BEGIN")
                opened.append(store)
                # Pin the same WAL snapshot for vectors, metadata, FTS and jump targets.
                store.db.execute("SELECT value FROM meta LIMIT 1").fetchone()
            reply = await self._search(q, kinds=kinds, query_result=query_result, begun=begun,
                                       legs=legs, limit=limit, seq=seq)
            if code is not None:
                items = sorted(reply["items"] + code["items"],
                               key=lambda item: (-item["score"], item["id"]))[:limit]
                for item in items:
                    item["weak"] = item["score"] < items[0]["score"] * 0.5
                reply.update(items=items, total=reply["total"] + code["total"],
                             weaker=sum(item["weak"] for item in items),
                             degraded=reply["degraded"] or code["degraded"])
                for field in ("embed", "words", "scan"):
                    reply["ms"][field] = round(reply["ms"][field] + code["ms"][field], 3)
                reply["ms"]["total"] = round((time.monotonic() - begun) * 1000, 3)
            return reply
        finally:
            for store in opened:
                store.db.rollback()

    async def _search(self, q: str, *, kinds, query_result, begun, legs, limit, seq) -> dict:
        words = query_terms(q)
        keyword, coverage, words_ms = await self._words(
            words if "words" in legs else [], kinds
        )
        vector, degraded, embed_ms = query_result
        scan_begun = time.monotonic()
        best = {}
        if vector is not None:
            self.reload()
        if vector is not None and len(self.matrix):
            scores = self.matrix @ vector
            zs = meaning(scores, self.columns["modality"], self.columns["scale"],
                         groups=self._modality_groups)
            indices = np.arange(len(zs))
            if kinds is not None:
                indices = indices[np.isin(self.columns["file_kind"], kinds)]
            codes = self.columns["file_code"][indices]
            order = np.lexsort((indices, -zs[indices], codes))
            _, first = np.unique(codes[order], return_index=True)
            winners = indices[order[first]]
            word_codes = [
                self._volume_codes[volume] << 40 | file
                for (volume, file), share in coverage.items() if share >= 0.5
            ]
            candidates = (zs[winners] >= 2) | np.isin(
                self.columns["file_code"][winners], word_codes
            )
            for index in winners[candidates]:
                key = str(self.columns["volume"][index]), int(self.columns["file"][index])
                best[key] = float(zs[index]), int(index)
        scan_ms = (time.monotonic() - scan_begun) * 1000
        candidates = {key for key, (z, _) in best.items() if z >= 2}
        candidates.update(key for key, share in coverage.items() if share >= 0.5)
        hinted = {KIND_WORDS[word] for word in terms(q) if word in KIND_WORDS}
        stores = {store.volume: store for store in self.stores}
        scored = [
            (
                fused_score(
                    best.get(key, (0,))[0],
                    coverage.get(key, 0),
                    lookup=is_lookup(q),
                    hinted=(
                        self.columns["file_kind"][best[key][1]]
                        if key in best else keyword[key]["file_kind"]
                    ) in hinted,
                ),
                key,
            )
            for key in candidates
        ]
        scored.sort(key=lambda item: (-item[0], item[1]))
        items = []
        for score, key in scored[:limit]:
            store = stores[key[0]]
            file = store.db.execute("SELECT * FROM files WHERE id=?", (key[1],)).fetchone()
            semantic, word = best.get(key), keyword.get(key)
            use_meaning = semantic is not None and (semantic[0] >= 2 or word is None)
            if word and word["kind"] == "ocr":
                use_meaning = False
            segment_id = int(self.columns["id"][semantic[1]]) if use_meaning else word["id"]
            segment = store.db.execute(
                "SELECT id,kind,loc,loc_end,excerpt FROM segments WHERE id=?", (segment_id,)
            ).fetchone()
            meaning_hit = semantic is not None and semantic[0] >= 2
            leg = (
                "meaning + words" if meaning_hit and word else "meaning" if meaning_hit else "words"
            )
            path = Path(os.path.abspath(store.mount / file["path"]))
            info = json.loads(file["info"] or "{}")
            marked = segment["excerpt"]
            if word and word["id"] == segment["id"]:
                marked = store.db.execute(
                    "SELECT snippet(fts,1,'«','»','…',12) FROM fts WHERE rowid=? AND fts MATCH ?",
                    (segment["id"], " OR ".join(map(pattern, words))),
                ).fetchone()[0]
            hits = []
            for term in words:
                if word:
                    match = store.db.execute(
                        "SELECT 1 FROM fts WHERE rowid=? AND fts MATCH ?",
                        (segment["id"], pattern(term)),
                    ).fetchone()
                    if match:
                        hits.append(term)
            items.append(
                {
                    "id": f"{store.volume}:{file['id']}:{segment['id']}",
                    "kind": file["kind"],
                    "path": str(path),
                    "name": path.name,
                    "dir": str(path.parent),
                    "volume": store.volume,
                    "label": store.label,
                    "offline": False,
                    "loc": segment["loc"],
                    "loc_end": segment["loc_end"],
                    "open_line": None,
                    "leg": leg,
                    "part": "image"
                    if segment["kind"] == "page_image"
                    else "speech"
                    if segment["kind"] == "audio" and file["kind"] == "video"
                    else segment["kind"]
                    if segment["kind"] in ("name", "ocr", "frame", "image", "audio")
                    else "text",
                    "z": semantic[0] if semantic else None,
                    "score": score,
                    "weak": bool(scored and score < scored[0][0] * 0.5),
                    "hits": hits,
                    "snippet": snippet_parts(marked or ""),
                    "thumb": info.get("thumb"),
                    "mtime": file["mtime"],
                    "size": file["size"],
                    "info": info,
                }
            )
        return {
            "t": "results",
            "seq": seq,
            "legs": list(legs),
            "ms": {
                "embed": round(embed_ms, 3),
                "scan": round(scan_ms, 3),
                "words": round(words_ms, 3),
                "total": round((time.monotonic() - begun) * 1000, 3),
            },
            "total": len(scored),
            "weaker": sum(item["weak"] for item in items),
            "degraded": degraded,
            "items": items,
        }
