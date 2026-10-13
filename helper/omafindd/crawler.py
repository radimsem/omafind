from collections import Counter

from .reconcile import reconcile
from .store import Store


def crawl(
    store: Store, roots: list[dict], *, force=False, skipped: Counter | None = None
) -> list[int]:
    return reconcile(store, roots, force=force, skipped=skipped).queued
