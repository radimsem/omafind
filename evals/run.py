#!/usr/bin/env python3
import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "helper"))
sys.path.insert(0, str(ROOT / "tests"))

from fakes.embedder import FakeEmbedder  # noqa: E402
from omafindd import paths  # noqa: E402
from omafindd.code import CodeStore  # noqa: E402
from omafindd.crawler import crawl  # noqa: E402
from omafindd.embedder import Embedder  # noqa: E402
from omafindd.embedding import Adapter  # noqa: E402
from omafindd.jobs import Jobs  # noqa: E402
from omafindd.search import Searcher  # noqa: E402
from omafindd.store import Store, volume_for  # noqa: E402


async def evaluate(searcher, queries, base, gate=1.0):
    return await evaluate_sets(searcher, [(queries, base)], gate)


async def evaluate_sets(searcher, query_sets, gate=1.0):
    counts = defaultdict(lambda: [0, 0])
    for queries, base in query_sets:
        for query in queries:
            reply = await searcher.search(query["q"], limit=1)
            expected = {(base / path).resolve() for path in query["expect"]}
            first = bool(reply["items"] and Path(reply["items"][0]["path"]).resolve() in expected)
            counts[query["tag"]][0] += int(first)
            counts[query["tag"]][1] += 1
    total = [sum(value[index] for value in counts.values()) for index in (0, 1)]
    for tag, (hits, size) in [*sorted(counts.items()), ("total", total)]:
        print(f"first-hit {tag} {hits}/{size} ({100 * hits / max(size, 1):.1f}%)")
    return total[1] > 0 and total[0] / total[1] >= gate


async def run(args):
    query_paths = [args.queries] if isinstance(args.queries, Path) else args.queries
    configs = [json.loads(path.read_text()) for path in query_paths]
    query_sets = [(config["queries"], Path(config["base"]).expanduser().resolve())
                  for config in configs]
    base = query_sets[0][1]
    stores = []
    code_directory, code_roots = None, ()
    embedder = (
        FakeEmbedder()
        if args.index is None
        else Adapter(Embedder(binary=paths.runtime_bin(), model_dir=paths.model_dir()))
    )
    try:
        with tempfile.TemporaryDirectory(prefix="omafind-eval-") as temporary:
            if args.index is None:
                base = Path(
                    shutil.copytree(ROOT / "tests/fixtures/corpus", Path(temporary) / "corpus")
                )
                query_sets = [(queries, base) for queries, _ in query_sets]
                store = Store(
                    Path(temporary) / "index/fixture.sqlite", volume="fixture", mount=base
                )
                stores.append(store)
                crawl(store, [{"path": str(base), "excludes": []}])
                await Jobs(store, embedder, journal=Path(temporary) / "journal").drain()
            else:
                code_directory = args.index.parent if args.index.is_file() else args.index
                code_path = code_directory / "code.sqlite"
                if code_path.is_file():
                    code = CodeStore.open_existing(code_path.resolve(), Path("/"))
                    try:
                        row = code.db.execute(
                            "SELECT value FROM meta WHERE key='code_roots'"
                        ).fetchone()
                        code_roots = tuple(Path(root) for root in json.loads(row[0])) if row else ()
                    finally:
                        code.close()
                databases = (
                    [args.index] if args.index.is_file() else sorted(args.index.glob("*.sqlite"))
                )
                if any(path.name != "code.sqlite" for path in databases):
                    _, mount = volume_for(base)
                stores.extend(
                    Store.open_existing(path.resolve(), mount)
                    for path in databases
                    if path.name != "code.sqlite"
                )
            searcher = Searcher(stores, embedder, code_directory=code_directory,
                                code_roots=code_roots)
            return 0 if await evaluate_sets(searcher, query_sets, args.gate) else 1
    finally:
        await embedder.stop()
        for store in stores:
            store.close()


def main():
    parser = argparse.ArgumentParser(
        description="First-hit evals; without --index uses offline fixtures"
    )
    parser.add_argument("--index", type=Path)
    parser.add_argument("--queries", type=Path, action="append", required=True,
                        help="Query file; repeat to score one combined set")
    parser.add_argument("--gate", type=float, default=0.9,
                        help="Minimum total first-hit fraction (default: 0.9)")
    args = parser.parse_args()
    if not 0 <= args.gate <= 1:
        parser.error("--gate must be between 0 and 1")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
