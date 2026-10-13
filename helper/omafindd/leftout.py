import os
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import rules

PRECEDENCE = ('secrets', 'user', 'generated', 'no-kind')


@dataclass(frozen=True, slots=True)
class Listed:
    path: str
    kind: str | None
    secret: bool


def pattern(stems: Sequence[str], ext: str) -> str:
    def template(stem):
        return re.sub(r'\d+', lambda m: 'YYYYMMDD' if len(m[0]) == 8
                      and m[0][:2] in ('19', '20') else '#' * len(m[0]), stem)

    templates = Counter(template(stem) for stem in stems)
    common = templates.most_common(1)[0][0] if templates else ''
    return common + ext


def extension(path: str) -> str:
    return _extension(os.path.basename(path))


@lru_cache(maxsize=65536)
def _extension(name: str) -> str:
    index = name.rfind('.')
    if index <= 0 or index == len(name) - 1:
        return ''
    suffix = name[index:]
    stem = name[:index].lstrip('.')
    previous_index = stem.rfind('.')
    previous = stem[previous_index:] if previous_index > 0 else ''
    return (previous + suffix if previous == '.tar' else suffix).lower()


def histogram(values) -> list[list]:
    counts = Counter(values)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [[name, n] for name, n in ordered[:3]]


def proposals(files: Sequence[Listed], *, own=None) -> list[dict]:
    if own is None:
        own = defaultdict(list)
        for file in files:
            if not file.secret:
                own[file.path.rpartition('/')[0] or '.'].append(file)
    totals = Counter({parent: len(items) for parent, items in own.items()})
    content_totals = Counter({parent: sum(bool(f.kind) for f in items)
                              for parent, items in own.items()})
    dirs = set()
    for parent in own:
        while parent != '.':
            dirs.add(parent)
            parent = parent.rpartition('/')[0] or '.'
    ordered = sorted(dirs, key=lambda p: p.count('/'), reverse=True)
    for path in ordered:
        parent = path.rpartition('/')[0] or '.'
        totals[parent] += totals[path]
        content_totals[parent] += content_totals[path]
    extensions = defaultdict(Counter, {
        parent: Counter(extension(f.path) for f in items)
        for parent, items in own.items() if not content_totals[parent]})
    for path in ordered:
        parent = path.rpartition('/')[0] or '.'
        if not content_totals[parent]:
            extensions[parent].update(extensions[path])
    result = []
    no_kind = {path for path in dirs if totals[path] >= 20 and not content_totals[path]}
    for path in sorted(no_kind):
        parent = path.rpartition('/')[0]
        covered = False
        while parent:
            if parent in no_kind:
                covered = True
                break
            parent = parent.rpartition('/')[0]
        if covered:
            continue
        result.append({'path': path, 'rule': 'no-kind', 'evidence': {
            'files': totals[path], 'exts': [[ext, n] for ext, n in sorted(
                extensions[path].items(), key=lambda item: (-item[1], item[0]))[:3]],
            'searchable': 0}})
    for path, items in own.items():
        # The root's own files are never left out, as with no-kind (D4).
        if path == '.':
            continue
        content = [f for f in items if f.kind]
        if len(content) < 20:
            continue
        counts = Counter(f.kind for f in content)
        if any(n >= 300 for n in counts.values()):
            continue
        machine = [f for f in content if rules.looks_machine_named(
            os.path.splitext(os.path.basename(f.path))[0])]
        if len(machine) / len(content) < .7:
            continue
        ext = Counter(extension(f.path) for f in machine).most_common(1)[0][0]
        result.append({'path': path, 'rule': 'generated', 'evidence': {
            'pattern': pattern([os.path.splitext(os.path.basename(f.path))[0]
                                for f in machine], ext),
            'match': [len(machine), len(content)], 'dataset_limit': 300}})
    return sorted(result, key=lambda e: e['path'])


def ledger(files: Sequence[Listed], excludes: Sequence[dict]) -> dict:
    entries = [dict(e, counts=dict.fromkeys(rules.INDEXED_KINDS, 0), files=0) for e in excludes]
    found = dict.fromkeys(rules.INDEXED_KINDS, 0)
    kept = dict.fromkeys(rules.INDEXED_KINDS, 0)
    secret_counts = dict.fromkeys(rules.INDEXED_KINDS, 0)
    secrets = []
    ranked = [(PRECEDENCE.index(e['rule']), len(Path(e['path']).parts), i)
              for i, e in enumerate(entries)]
    by_path = defaultdict(list)
    for i, entry in enumerate(entries):
        by_path[os.path.normpath(entry['path']).strip('/') if entry['path'] not in ('', '.')
                else ''].append(i)
    parent_owners = {}

    def owner_of(path):
        trail = []
        while path not in parent_owners:
            trail.append(path)
            if not path:
                break
            path = path.rpartition('/')[0]
        owner = parent_owners.get(path)
        for ancestor in reversed(trail):
            matches = list(by_path.get(ancestor, ()))
            if owner is not None:
                matches.append(owner)
            owner = min(matches, key=ranked.__getitem__) if matches else None
            parent_owners[ancestor] = owner
        return owner

    for file in files:
        if file.secret:
            secrets.append(file)
        if file.kind is None:
            continue
        found[file.kind] += 1
        if file.secret:
            secret_counts[file.kind] += 1
            continue
        path = os.path.normpath(file.path).strip('/')
        parent_owner = owner_of(path.rpartition('/')[0])
        matches = list(by_path.get(path, ()))
        if parent_owner is not None:
            matches.append(parent_owner)
        if matches:
            owner = min(matches, key=ranked.__getitem__)
            entries[owner]['counts'][file.kind] += 1
            entries[owner]['files'] += 1
        else:
            kept[file.kind] += 1
    proposed = None
    for entry in entries:
        if entry['rule'] == 'user':
            entry['evidence'] = {'files': entry['files']}
        elif 'evidence' not in entry:
            if proposed is None:
                proposed = {e['path']: e['evidence'] for e in proposals(files)}
            entry['evidence'] = proposed.get(entry['path'], {})
    if secrets:
        families = Counter(rules.secret_family(next(
            (part for part in Path(f.path).parts if rules.reason(Path(part)) == 'secrets'),
            Path(f.path).name
        )) for f in secrets)
        entries.append({'path': '**', 'rule': 'secrets', 'files': sum(secret_counts.values()),
                        'counts': secret_counts, 'evidence': {
                            'exts': [[name, n] for name, n in sorted(
                                families.items(), key=lambda item: (-item[1], item[0]))],
                            'in': sorted({os.path.dirname(f.path) for f in secrets})}})
    return {'found': sum(found.values()), 'kept': sum(kept.values()),
            'found_counts': found, 'counts': kept, 'left_out': entries, 'dirs': len(excludes)}
