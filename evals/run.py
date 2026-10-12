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
from omafindd.crawler import crawl  # noqa: E402
from omafindd.embedder import Embedder  # noqa: E402
from omafindd.embedding import Adapter  # noqa: E402
from omafindd.jobs import Jobs  # noqa: E402
from omafindd.search import Searcher  # noqa: E402
from omafindd.store import Store, volume_for  # noqa: E402


async def evaluate(searcher, queries, base):
    counts = defaultdict(lambda: [0, 0])
    for query in queries:
        reply = await searcher.search(query["q"], limit=1)
        expected = {(base / path).resolve() for path in query["expect"]}
        first = bool(reply["items"] and Path(reply["items"][0]["path"]).resolve() in expected)
        counts[query["tag"]][0] += int(first)
        counts[query["tag"]][1] += 1
    total = [sum(value[index] for value in counts.values()) for index in (0, 1)]
    for tag, (hits, size) in [*sorted(counts.items()), ("total", total)]:
        print(f"first-hit {tag} {hits}/{size} ({100 * hits / max(size, 1):.1f}%)")
    return total[0] == total[1]


async def run(args):
    config = json.loads(args.queries.read_text())
    base = Path(config["base"]).expanduser().resolve()
    stores = []
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
                store = Store(
                    Path(temporary) / "index/fixture.sqlite", volume="fixture", mount=base
                )
                stores.append(store)
                crawl(store, [{"path": str(base), "excludes": []}])
                await Jobs(store, embedder, journal=Path(temporary) / "journal").drain()
            else:
                _, mount = volume_for(base)
                databases = (
                    [args.index] if args.index.is_file() else sorted(args.index.glob("*.sqlite"))
                )
                stores.extend(
                    Store.open_existing(path.resolve(), mount)
                    for path in databases
                    if path.name != "code.sqlite"
                )
            return 0 if await evaluate(Searcher(stores, embedder), config["queries"], base) else 1
    finally:
        await embedder.stop()
        for store in stores:
            store.close()


def main():
    parser = argparse.ArgumentParser(
        description="First-hit evals; without --index uses offline fixtures"
    )
    parser.add_argument("--index", type=Path)
    parser.add_argument("--queries", type=Path, required=True)
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
