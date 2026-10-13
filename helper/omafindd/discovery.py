import json
import os
import re
import subprocess
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import cache, lru_cache
from pathlib import Path

from . import leftout, rules

KINDS = ('text', 'pdf', 'image', 'video', 'audio')
RATES = {
    'gpu': {'text': .07, 'pdf': .37, 'image': .14, 'video': 3.2, 'audio': 1.5, 'code': .042},
    'cpu': {'text': .13, 'pdf': .54, 'image': 1.36, 'video': 18., 'audio': 11.1, 'code': .084},
    'bytes': {'text': 11000, 'pdf': 48000, 'image': 7000, 'video': 40000,
              'audio': 12000, 'code': 10000},
}


@dataclass
class RootTree:
    candidate: dict
    dirs: list[dict]
    secrets: dict


@dataclass
class Scan:
    body: dict
    roots: dict[str, RootTree]
    scanned_at: float


def estimate(counts: dict, device: str) -> tuple[int, float]:
    return (sum(n * RATES['bytes'][k] for k, n in counts.items()),
            sum(n * RATES[device][k] for k, n in counts.items()))


def non_system_volumes(lsblk_json: dict) -> list[tuple[str, Path]]:
    def entries(devices):
        for device in devices:
            yield device
            yield from entries(device.get('children', []))

    devices = list(entries(lsblk_json.get('blockdevices', [])))
    system = {'/', '/boot', '/home', '[SWAP]'}
    for device in devices:
        mounts = device.get('mountpoints') or []
        if device.get('fstype') == 'btrfs' and '/' in mounts:
            system.update(m for m in mounts if m)
    volumes = []
    for device in devices:
        uuid = device.get('uuid')
        for mount in device.get('mountpoints') or []:
            if uuid and mount and mount != '[SWAP]' and (
                mount not in system or device.get('rm') or device.get('hotplug')
            ):
                item = (uuid, Path(mount))
                if item not in volumes:
                    volumes.append(item)
                break
    return volumes


def xdg_dirs(home: Path) -> dict[str, Path]:
    try:
        text = (home / '.config/user-dirs.dirs').read_text()
    except FileNotFoundError:
        return {}
    result = {}
    for name, value in re.findall(r'^XDG_(\w+)_DIR="([^"]*)"', text, re.MULTILINE):
        path = Path(value.replace('${HOME}', str(home)).replace('$HOME', str(home)))
        if path.is_absolute() and path != home:
            result[name] = path
    return result


def candidates(counts: dict[Path, dict], *, home: Path, volume_roots: set[Path],
               xdg: set[Path]) -> list[tuple[Path, str]]:
    forbidden = {home, *volume_roots}
    totals = {path: sum(value.values()) for path, value in counts.items()}
    dense = {path for path, total in totals.items() if total >= 20 and path not in forbidden}
    selected = set()
    dense_parents = {path.parent for path in dense}
    for path in sorted(dense):
        if path in dense_parents:
            continue
        while path.parent not in forbidden and path.parent in totals and (
            totals[path] >= .6 * totals[path.parent]
        ):
            path = path.parent
        selected.add(path)
    selected = {path for path in selected if not any(parent in selected for parent in path.parents)}
    homes = {path for path in xdg if path not in forbidden and totals.get(path, 0)}
    selected = {path for path in selected if not any(path.is_relative_to(x) for x in homes)}
    return [(path, 'home') for path in sorted(homes)] + [
        (path, 'elsewhere') for path in sorted(selected) if path not in homes]


def _listing(root, run, paths=None):
    args = ['fd', '--threads', '8', '-0', '-t', 'f', '-H', '--one-file-system',
            '--no-global-ignore-file']
    for glob in rules.HEAVY_GLOBS:
        args.extend(['-E', glob])
    if rules.reason(root.absolute()) is not None:
        args.extend(['-E', '*'])
    result = run([*args, '.', *(str(p) for p in (paths or [root]))],
                 cwd=root, capture_output=True, check=True)
    return [os.fsdecode(name) for name in result.stdout.split(b'\0') if name]


def _listed(root, run, datasets=(), *, names=None):
    names = _listing(root, run) if names is None else names
    datasets = {str(p) for p in datasets}
    files = []
    folders = {}
    prefix = str(root).rstrip('/') + '/'
    for absolute in names:
        parent, _, basename = absolute.rpartition('/')
        if parent not in folders:
            ancestor = parent
            while ancestor and ancestor not in datasets:
                ancestor = os.path.dirname(ancestor) if ancestor != '/' else ''
            folder = parent[len(prefix):] if parent.startswith(prefix) else ''
            folders[parent] = (ancestor in datasets, rules.reason(Path(folder)))
        excluded, parent_why = folders[parent]
        if excluded:
            continue
        rel = (absolute[len(prefix):] if absolute.startswith(prefix)
               else os.path.relpath(absolute, root))
        name_why = rules.reason_name(basename)
        why = ('secrets' if 'secrets' in (parent_why, name_why) else
               'heavy' if 'heavy' in (parent_why, name_why) else parent_why or name_why)
        if why in ('dot', 'heavy'):
            continue
        files.append(leftout.Listed(rel, rules.classify_name(basename), why == 'secrets'))
    skipped = rules.datasets([f.path for f in files if not f.secret and f.kind],
                             root=Path('.'))
    if not skipped:
        return files
    excluded = {f.path: any(p in skipped for p in Path(f.path).parents) for f in files}
    return [f for f in files if not excluded[f.path]]


def _root_tree(root, files, *, section, volume, git, device):
    own_files = defaultdict(list)
    own = defaultdict(Counter)
    own_total = Counter()
    extensions = defaultdict(Counter)
    for file in files:
        if file.secret:
            continue
        parent = file.path.rpartition('/')[0]
        own_files[parent or '.'].append(file)
        own_total[parent] += 1
        if file.kind:
            own[parent][file.kind] += 1
            extensions[parent][leftout.extension(file.path)] += 1
    sub = {path: value.copy() for path, value in own.items()}
    totals = own_total.copy()
    exts = {path: value.copy() for path, value in extensions.items()}
    dir_counts = Counter()
    for path in own_total:
        parent = path
        while True:
            dir_counts[parent] = 1
            sub.setdefault(parent, Counter())
            exts.setdefault(parent, Counter())
            if not parent:
                break
            parent = parent.rpartition('/')[0]
    for path in sorted(dir_counts, key=lambda p: p.count('/') + bool(p), reverse=True):
        if path:
            parent = path.rpartition('/')[0]
            sub[parent].update(sub[path])
            totals[parent] += totals[path]
            exts[parent].update(exts[path])
            dir_counts[parent] += dir_counts[path]
    proposed = leftout.proposals(files, own=own_files)
    result = leftout.ledger(files, proposed)
    proposals_by_path = {e['path']: e for e in proposed}
    dirs = []
    for path in sorted(dir_counts):
        proposal = proposals_by_path.get(path)
        dirs.append({'path': path,
                     'own': {k: own[path][k] for k in KINDS},
                     'all_own': own_total[path],
                     'sub': {k: sub[path][k] for k in KINDS},
                     'all_sub': totals[path], 'dirs': dir_counts[path],
                     'exts': [[name, n] for name, n in sorted(
                         exts[path].items(), key=lambda item: (-item[1], item[0]))[:3]],
                     'rule': proposal['rule'] if proposal else None,
                     'evidence': proposal['evidence'] if proposal else None})
    if not dirs:
        dirs = [{'path': '', 'own': dict.fromkeys(KINDS, 0), 'all_own': 0,
                 'sub': dict.fromkeys(KINDS, 0), 'all_sub': 0, 'dirs': 1,
                 'exts': [], 'rule': None, 'evidence': None}]
    excludes = [e['path'] for e in proposed]
    excluded_folders = set(excludes)
    kept_parents = {}
    for file in files:
        if not file.kind or file.secret:
            continue
        parent = file.path.rpartition('/')[0]
        if parent not in kept_parents:
            ancestor = parent
            while ancestor and ancestor not in excluded_folders:
                ancestor = os.path.dirname(ancestor)
            kept_parents[parent] = ancestor not in excluded_folders
    kept_exts = leftout.histogram(leftout.extension(f.path) for f in files
                                 if f.kind and not f.secret
                                 and kept_parents[os.path.dirname(f.path)])
    index_bytes, seconds = estimate(result['counts'], device)
    candidate = {'path': str(root), 'section': section, 'checked': section == 'home',
                 'volume': volume, 'git': git, 'dirs': dirs[0]['dirs'],
                 **{k: result[k] for k in ('found', 'kept', 'found_counts', 'counts', 'left_out')},
                 'exts': kept_exts, 'excludes': excludes, 'index_bytes': index_bytes,
                 'seconds': seconds}
    secret_entry = next((e for e in result['left_out'] if e['rule'] == 'secrets'), None)
    secrets = {k: secret_entry[k] for k in ('files', 'counts', 'evidence')} if secret_entry else {
        'files': 0, 'counts': dict.fromkeys(KINDS, 0), 'evidence': {'exts': [], 'in': []}}
    return RootTree(candidate, dirs, secrets)


def _repos(roots, run, device):
    from .code import (
        CODE_FILE_NAMES,
        SKIPPED_FOLDERS,
        SOURCE_EXTENSIONS,
        TEXT_EXTENSIONS,
        classify_code,
    )

    code_extensions = SOURCE_EXTENSIONS | TEXT_EXTENSIONS | {'ipynb'}

    @lru_cache(maxsize=131072)
    def details(raw):
        name = os.fsdecode(raw)
        parts = tuple(name.split('/'))
        why = rules.reason_parts(parts)
        skipped = any(part in SKIPPED_FOLDERS for part in parts[:-1])
        basename = parts[-1]
        index = basename.rfind('.')
        extension = basename[index + 1:].lower() if index > 0 else ''
        eligible = (extension in code_extensions or basename in CODE_FILE_NAMES
                    or basename.startswith('Dockerfile'))
        code = classify_code(Path(name)) if eligible and not why and not skipped else False
        return code, why == 'secrets', skipped
    paths = set()
    for root in roots:
        args = ['fd', '--threads', '8', '-0', '-H', '-I', '-t', 'd', '-t', 'f', '--prune',
                '--no-global-ignore-file']
        for glob in rules.HEAVY_GLOBS:
            if glob != '.git':
                args.extend(['-E', glob])
        found = run([*args, r'^\.git$', str(root)], cwd=root, capture_output=True, check=True)
        paths.update(Path(os.fsdecode(name)).parent for name in found.stdout.split(b'\0') if name)

    def list_repo(path):
        try:
            listed = run(['git', '-C', str(path), 'ls-files', '-z'],
                         capture_output=True, check=True)
        except subprocess.CalledProcessError:
            return None
        return listed.stdout

    def inspect(path, output):
        names = [n for n in output.split(b'\0') if n]
        code_files = 0
        secrets = generated = False
        for raw in names:
            code, secret, skipped = details(raw)
            code_files += code
            secrets |= secret
            generated |= skipped
        triggered = []
        if secrets:
            triggered.append('secrets')
        if generated:
            triggered.append('generated')
        size, seconds = estimate({'code': code_files}, device)
        return {'path': str(path), 'tracked': len(names), 'code_files': code_files,
                'rules': triggered, 'index_bytes': size, 'seconds': seconds}

    ordered = sorted(paths)
    with ThreadPoolExecutor(max_workers=24) as pool:
        outputs = list(pool.map(list_repo, ordered))
    return [inspect(path, output) for path, output in zip(ordered, outputs, strict=True)
            if output is not None]


def _device(home):
    from .embedder import free_vram
    from .settings import load

    settings = load(home / '.config/omarchy/shell.json')
    if settings.gpu == 'never':
        return 'cpu'
    free = free_vram()
    return 'cpu' if free is not None and free < 1536 else 'gpu'


def _volume_of(path):
    from .store import volume_for

    return volume_for(path)


def _volume_lookup(lsblk):
    from .store import mounted_volumes

    mounts = {mount: uuid for uuid, mount in mounted_volumes().items()}

    def collect(devices):
        for device in devices:
            if device.get('uuid'):
                for mount in device.get('mountpoints') or []:
                    if mount and mount.startswith('/'):
                        mounts[Path(mount)] = device['uuid']
            collect(device.get('children', []))

    collect(lsblk.get('blockdevices', []))
    ordered = sorted(mounts, key=lambda p: len(p.parts), reverse=True)

    def lookup(path):
        for mount in ordered:
            if path.is_relative_to(mount):
                return mounts[mount], mount
        return _volume_of(path)

    return lookup


def scan(*, home: Path, volume: str | None = None, run=subprocess.run, popen=subprocess.Popen,
         lsblk=None, volume_of=None, xdg=None, device=None, clock=time.monotonic,
         now=time.time) -> Scan:
    started = clock()
    home = home.absolute()
    if lsblk is None:
        result = run(['lsblk', '-J', '-o', 'UUID,LABEL,FSTYPE,SIZE,RM,HOTPLUG,MOUNTPOINTS'],
                     capture_output=True, check=True)
        lsblk = json.loads(result.stdout)
    volumes = non_system_volumes(lsblk)
    if volume is not None:
        volumes = [(uuid, path) for uuid, path in volumes if uuid == volume]
    walk_roots = ([home] if volume is None else []) + [p for _, p in volumes]
    xdg = xdg_dirs(home) if xdg is None else xdg
    counts = defaultdict(lambda: dict.fromkeys(KINDS, 0))
    datasets = set()
    dataset_details = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        volume_future = pool.submit(_volume_lookup, lsblk) if volume_of is None else None
        device_future = pool.submit(_device, home) if device is None else None

        def repo_scan():
            chosen_device = device_future.result() if device_future is not None else device
            return _repos(walk_roots, run, chosen_device)

        repo_future = pool.submit(repo_scan)
        # Baseline files have no dot/heavy ancestor, so cannot contribute to rule_dirs.
        removed = {r: pool.submit(rules.removed, home, r, run=run, as_paths=False, baseline=())
                   for r in ('dot', 'heavy')} if volume is None else {}
        for root in walk_roots:
            listed = list(rules.walk(root, excludes=[], run=popen))
            skipped = rules.datasets(listed, root=root)
            datasets.update(skipped)
            for folder in skipped:
                names = [p for p in listed if p.is_relative_to(folder)]
                matched = sum(rules.looks_machine_named(p.stem) for p in names)
                dataset_details[str(folder)] = {"path": str(folder), "files": len(names),
                                                "match": [matched, len(names)]}
            direct = defaultdict(Counter)
            skipped_names = {str(p) for p in skipped}
            excluded = {}
            for file in listed:
                name = str(file)
                parent = os.path.dirname(name)
                if parent not in excluded:
                    ancestor = parent
                    while ancestor and ancestor not in skipped_names:
                        ancestor = os.path.dirname(ancestor) if ancestor != '/' else ''
                    excluded[parent] = ancestor in skipped_names
                if not excluded[parent]:
                    direct[parent][rules.classify_name(os.path.basename(name))] += 1
            root_name = str(root)
            rolled = {directory: values.copy() for directory, values in direct.items()
                      if directory == root_name
                      or directory.startswith(root_name.rstrip('/') + '/')}
            for directory in list(rolled):
                if directory == root_name:
                    continue
                parent = directory.rpartition('/')[0] or '/'
                while parent not in rolled:
                    rolled[parent] = Counter()
                    if parent == root_name:
                        break
                    parent = parent.rpartition('/')[0] or '/'
            for directory in sorted(rolled, key=lambda p: p.count('/'), reverse=True):
                if directory != root_name:
                    rolled[directory.rpartition('/')[0] or '/'].update(rolled[directory])
            for directory, values in rolled.items():
                target = counts[Path(directory)]
                for kind, n in values.items():
                    target[kind] += n
        selected = candidates(counts, home=home, volume_roots={p for _, p in volumes},
                              xdg=set(xdg.values()) if volume is None else set())
        selected_names = {str(path): [] for path, _ in selected}
        listings = [pool.submit(_listing, root, run, paths) for root in walk_roots
                    if (paths := [p for p, _ in selected if p.is_relative_to(root)])]
        @cache
        def owners(parent):
            if not parent:
                return ()
            if parent.count('/') > 256:
                matches = []
                while parent:
                    if parent in selected_names:
                        matches.append(parent)
                    parent = parent.rpartition('/')[0] if parent != '/' else ''
                return tuple(reversed(matches))
            ancestors = owners(parent.rpartition('/')[0] if parent != '/' else '')
            return (*ancestors, parent) if parent in selected_names else ancestors

        seen = set()
        for future in listings:
            for name in future.result():
                if name in seen:
                    continue
                seen.add(name)
                for parent in owners(name.rpartition('/')[0]):
                    selected_names[parent].append(name)
        roots = {}
        if volume_future is not None:
            volume_of = volume_future.result()
        if device_future is not None:
            device = device_future.result()
        for path, section in selected:
            data = _root_tree(path, _listed(path, run, datasets, names=selected_names[str(path)]),
                              section=section, volume=volume_of(path)[0], device=device, git=False)
            if volume is not None:
                data.candidate["checked"] = True
            roots[str(path)] = data
        rule_counts = {r: rules.rule_dirs(future.result(), r, root=home)
                       for r, future in removed.items() if r != 'secrets'}
        repos = repo_future.result()
    repo_paths = {Path(r['path']) for r in repos}
    for path, _ in selected:
        roots[str(path)].candidate['git'] = path in repo_paths or any(
            p in repo_paths for p in path.parents)
    scanned_at = now()
    body = {'home': str(home), 'device': device,
            'scan': {'seconds': clock() - started, 'dirs': len(counts), 'volumes': len(volumes),
                     'roots': (['$HOME'] if volume is None else []) + [str(p) for _, p in volumes],
                     'scanned_at': scanned_at},
            'rates': RATES, 'candidates': [r.candidate for r in roots.values()], 'repos': repos,
            'not_proposed': {'no_kind': sorted(str(p) for p in xdg.values()
                                             if p != home and not sum(counts.get(p, {}).values()))
                            if volume is None else [],
                            'dot': rule_counts.get('dot', 0), 'heavy': rule_counts.get('heavy', 0),
                            'dataset': len(datasets),
                            'datasets': [dataset_details[p] for p in sorted(dataset_details)]}}
    return Scan(body, roots, scanned_at)


def _expand(path, home):
    if path == '~':
        return home
    return Path(os.path.abspath(home / path[2:] if path.startswith('~/') else path))


def tree(scan: Scan, root: str, *, home: Path, run=subprocess.run) -> dict:
    absolute = _expand(root, home)
    key = str(absolute)
    if key not in scan.roots:
        scan.roots[key] = _root_tree(
            absolute, _listed(absolute, run), section='elsewhere', volume=_volume_of(absolute)[0],
            git=any(absolute.is_relative_to(Path(r['path'])) for r in scan.body['repos']),
            device=scan.body['device'])
    data = scan.roots[key]
    return {'root': root, 'abs': key, 'scanned_at': scan.scanned_at, 'candidate': data.candidate,
            'secrets': data.secrets, 'dirs': data.dirs}


def list_dirs(path: str, *, home: Path) -> dict:
    absolute = _expand(path, home)
    result = {'path': path, 'abs': str(absolute), 'dirs': [], 'error': None}
    try:
        with os.scandir(absolute) as entries:
            result['dirs'] = sorted((entry.name for entry in entries
                                     if not entry.name.startswith('.')
                                     and entry.name not in rules.HEAVY_GLOBS
                                     and entry.is_dir()), key=lambda n: (n.casefold(), n))[:500]
    except FileNotFoundError:
        result['error'] = 'missing'
    except NotADirectoryError:
        result['error'] = 'not-a-directory'
    except PermissionError:
        result['error'] = 'denied'
    return result
