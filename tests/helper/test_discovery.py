import io
import json
import os
import subprocess
from pathlib import Path

import pytest
from omafindd import discovery, rules
from support.documents import make_documents


def counts(n):
    return dict.fromkeys(discovery.KINDS, 0) | {'text': n}


def test_25_file_directory_is_proposed_19_is_not():
    result = discovery.candidates({Path('/h/a'): counts(25), Path('/h/b'): counts(19)},
                                  home=Path('/h'), volume_roots=set(), xdg=set())
    assert result == [(Path('/h/a'), 'elsewhere')]


@pytest.mark.parametrize('ratio,path', [(59, '/h/p/a'), (60, '/h/p')])
def test_dense_subtree_at_59_percent_stops_below_parent(ratio, path):
    result = discovery.candidates({Path('/h/p/a'): counts(ratio), Path('/h/p'): counts(100)},
                                  home=Path('/h'), volume_roots=set(), xdg=set())
    assert result == [(Path(path), 'elsewhere')]


def test_home_and_volume_root_are_never_proposed():
    assert discovery.candidates({Path('/h'): counts(50), Path('/v'): counts(50)},
                                home=Path('/h'), volume_roots={Path('/v')}, xdg=set()) == []


def test_xdg_dirs_with_content_are_checked_others_unchecked(tmp_path):
    (tmp_path / 'Documents').mkdir()
    for folder, n in [('Documents', 3), ('elsewhere', 25)]:
        path = tmp_path / folder
        path.mkdir(exist_ok=True)
        for i in range(n):
            (path / f'reading-note-{i}.md').touch()
    scan = discovery.scan(home=tmp_path, lsblk={'blockdevices': []},
                          volume_of=lambda p: ('u', tmp_path),
                          xdg={'DOCUMENTS': tmp_path / 'Documents', 'MUSIC': tmp_path / 'Music'},
                          device='cpu')
    rows = [(Path(c['path']).name, c['section'], c['checked'])
            for c in scan.body['candidates']]
    assert rows == [
        ('Documents', 'home', True), ('elsewhere', 'elsewhere', False)]
    assert scan.body['not_proposed']['no_kind'] == [str(tmp_path / 'Music')]


class Process:
    def __init__(self, names):
        self.stdout = io.BytesIO(b'\0'.join(os.fsencode(name) for name in names) + b'\0')
        self.stderr = io.BytesIO()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def wait(self):
        return 0


def test_walk_is_one_fd_listing_per_volume_and_never_stats(monkeypatch):
    home, volume = Path('/fake-home'), Path('/fake-volume')
    calls = []

    def popen(argv, **kwargs):
        calls.append(argv)
        return Process([Path(argv[-1]) / f'docs/reading-note-{n}.md' for n in range(25)])

    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, b'', b'')

    original_stat, original_lstat = os.stat, os.lstat

    def guard(original):
        def stat(path, *args, **kwargs):
            if str(path).startswith(('/fake-home', '/fake-volume')):
                raise AssertionError('scan must never stat listed paths')
            return original(path, *args, **kwargs)
        return stat

    monkeypatch.setattr(os, 'stat', guard(original_stat))
    monkeypatch.setattr(os, 'lstat', guard(original_lstat))
    body = discovery.scan(home=home, popen=popen, run=run,
                          lsblk={'blockdevices': [{'uuid': 'v', 'mountpoints': [str(volume)]}]},
                          volume_of=lambda p: ('u', Path('/')), xdg={}, device='gpu').body
    assert len([argv for argv in calls if '-e' in argv]) == 2
    assert body['scan']['roots'] == ['$HOME', str(volume)]
    assert len(body['candidates']) == 2


def test_explain_counts_dot_heavy_secrets_by_name(tmp_path):
    for name in ('.a/a.md', '.b/a.md', 'build/a.md', 'visible/a.md', 'visible/secret.md'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    body = discovery.scan(home=tmp_path, lsblk={}, volume_of=lambda p: ('u', tmp_path),
                          xdg={}, device='cpu').body
    assert body['not_proposed']['dot'] == 2
    assert body['not_proposed']['heavy'] == 1
    assert rules.explain(tmp_path)['secrets'] == 1


def test_repositories_are_found_by_git_and_count_tracked_files(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    for name in ('main.py', 'notes.md', '.env'):
        (repo / name).touch()
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    body = discovery.scan(home=tmp_path, lsblk={}, volume_of=lambda p: ('u', tmp_path),
                          xdg={}, device='cpu').body
    assert body['repos'] == [{'path': str(repo), 'tracked': 3, 'code_files': 2,
                             'rules': ['secrets'], 'index_bytes': 20000, 'seconds': .168}]


def test_scan_body_shape_and_ledger_invariant(tmp_path):
    make_documents(tmp_path / 'Documents')
    body = discovery.scan(home=tmp_path, lsblk={}, volume_of=lambda p: ('u', tmp_path),
                          xdg={'DOCUMENTS': tmp_path / 'Documents'}, device='gpu').body
    assert set(body) == {'home', 'device', 'scan', 'rates', 'candidates', 'repos', 'not_proposed'}
    assert set(body['scan']) == {'seconds', 'dirs', 'volumes', 'roots', 'scanned_at'}
    candidate = body['candidates'][0]
    assert set(candidate) == {'path', 'section', 'checked', 'volume', 'git', 'dirs', 'found',
                              'kept', 'found_counts', 'counts', 'exts', 'excludes', 'left_out',
                              'index_bytes', 'seconds'}
    assert candidate['found'] == 899 and candidate['kept'] == 838
    assert candidate['found'] - sum(e['files'] for e in candidate['left_out']) == candidate['kept']
    assert all(set(candidate[key]) == set(discovery.KINDS) for key in ('counts', 'found_counts'))
    assert json.loads(json.dumps(body)) == body
    assert discovery.estimate(candidate['counts'], 'gpu') == (
        candidate['index_bytes'], candidate['seconds'])


def test_non_system_volumes_from_lsblk():
    data = {'blockdevices': [
        {'uuid': 'boot', 'mountpoints': ['/boot']},
        {'uuid': 'root', 'fstype': 'btrfs',
         'mountpoints': ['/', '/home', '/var/log', '/var/cache/pacman/pkg']},
        {'uuid': 'swap', 'mountpoints': ['[SWAP]']},
        {'uuid': 'container', 'mountpoints': [None]},
    ]}
    assert discovery.non_system_volumes(data) == []
    data['blockdevices'].append({'uuid': 'usb', 'fstype': 'exfat', 'hotplug': True,
                                 'mountpoints': ['/media/usb']})
    assert discovery.non_system_volumes(data) == [('usb', Path('/media/usb'))]


def test_list_dirs_hides_dot_and_heavy_and_reports_missing(tmp_path):
    for name in ('Zebra', 'apple', '.hidden', 'node_modules'):
        (tmp_path / name).mkdir()
    (tmp_path / 'file').touch()
    assert discovery.list_dirs('~', home=tmp_path) == {
        'path': '~', 'abs': str(tmp_path), 'dirs': ['apple', 'Zebra'], 'error': None}
    assert discovery.list_dirs('~/missing', home=tmp_path)['error'] == 'missing'
    assert discovery.list_dirs('~/file', home=tmp_path)['error'] == 'not-a-directory'


def test_list_dirs_reports_an_unreadable_directory(tmp_path, monkeypatch):
    def denied(path):
        raise PermissionError(13, 'Permission denied', str(path))

    monkeypatch.setattr(discovery.os, 'scandir', denied)
    assert discovery.list_dirs('/root', home=tmp_path) == {
        'path': '/root', 'abs': '/root', 'dirs': [], 'error': 'denied'}


def test_tree_dirs_carry_own_and_subtree_counts(tmp_path):
    root = tmp_path / 'Documents'
    make_documents(root)
    scan = discovery.scan(home=tmp_path, lsblk={}, volume_of=lambda p: ('u', tmp_path),
                          xdg={'DOCUMENTS': root}, device='gpu')
    body = discovery.tree(scan, '~/Documents', home=tmp_path)
    rows = {d['path']: d for d in body['dirs']}
    assert body['root'] == '~/Documents' and body['abs'] == str(root)
    assert body['secrets']['files'] == 3
    assert rows['tax/2024']['own'] == dict(zip(discovery.KINDS, (14, 22, 9, 0, 0), strict=True))
    assert rows['tax/2024']['all_own'] == rows['tax/2024']['all_sub'] == 45
    assert rows['work']['own'] == dict.fromkeys(discovery.KINDS, 0)
    assert rows['work']['sub']['text'] == 201
    assert rows['']['sub']['text'] == 803
    assert rows['archive/old-backups']['rule'] == 'no-kind'
    assert rows['vault/exports']['rule'] == 'generated'
    assert rows['']['dirs'] == len(rows)


def test_xdg_dirs_reads_home_and_omits_home_itself(tmp_path):
    config = tmp_path / '.config/user-dirs.dirs'
    config.parent.mkdir()
    config.write_text('XDG_DOCUMENTS_DIR="$HOME/Documents"\nXDG_MUSIC_DIR="${HOME}/Music"\n'
                      'XDG_DESKTOP_DIR="$HOME"\nXDG_TEMPLATES_DIR="$HOME"\n')
    assert discovery.xdg_dirs(tmp_path) == {
        'DOCUMENTS': tmp_path / 'Documents', 'MUSIC': tmp_path / 'Music'}


def test_volume_filter_scans_only_requested_volume():
    calls = []

    def popen(argv, **kwargs):
        calls.append(argv)
        return Process([])

    body = discovery.scan(
        home=Path('/h'), volume='two', xdg={}, device='cpu', popen=popen,
        run=lambda argv, **kw: subprocess.CompletedProcess(argv, 0, b'', b''),
        lsblk={'blockdevices': [{'uuid': 'one', 'mountpoints': ['/v1']},
                               {'uuid': 'two', 'mountpoints': ['/v2']}]},
        volume_of=lambda p: ('two', Path('/v2'))).body
    assert [argv[-1] for argv in calls] == ['/v2']
    assert body['scan']['roots'] == ['/v2'] and body['scan']['volumes'] == 1


def test_dataset_names_stay_out_of_found_tree_and_generated_entries(tmp_path):
    root = tmp_path / 'Documents'
    for folder, n in [('data', 300), ('data/nested', 1), ('kept', 25)]:
        path = root / folder
        path.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            (path / (f'clip_{i:06}.png' if folder == 'data' else f'reading-note-{i}.md')).touch()
    scan = discovery.scan(home=tmp_path, lsblk={}, volume_of=lambda p: ('u', tmp_path),
                          xdg={'DOCUMENTS': root}, device='cpu')
    candidate = scan.body['candidates'][0]
    assert candidate['found'] == candidate['kept'] == 25
    assert scan.body['not_proposed']['dataset'] == 1
    assert not any(d['path'].startswith('data') for d in scan.roots[str(root)].dirs)


def test_tree_scans_and_caches_uncovered_root(tmp_path, monkeypatch):
    root = tmp_path / 'picked'
    root.mkdir()
    (root / 'note.md').touch()
    scan = discovery.Scan({'device': 'cpu', 'repos': []}, {}, 12.)
    monkeypatch.setattr(discovery, '_volume_of', lambda p: ('u', tmp_path))
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.run(argv, **kwargs)

    body = discovery.tree(scan, '~/picked', home=tmp_path, run=run)
    assert body['candidate']['found'] == 1
    assert body['scanned_at'] == 12.
    assert discovery.tree(scan, str(root), home=tmp_path, run=run)['abs'] == str(root)
    assert len(calls) == 1


@pytest.mark.parametrize('folder', ['.hidden', 'secrets', 'build'])
def test_picked_root_obeys_global_rules(tmp_path, monkeypatch, folder):
    root = tmp_path / folder
    root.mkdir()
    (root / 'note.md').touch()
    scan = discovery.Scan({'device': 'cpu', 'repos': []}, {}, 12.)
    monkeypatch.setattr(discovery, '_volume_of', lambda p: ('u', tmp_path))
    assert discovery.tree(scan, str(root), home=tmp_path)['candidate']['found'] == 0


@pytest.mark.parametrize('marker', ['file', 'directory'])
def test_broken_repository_does_not_abort_scan(tmp_path, marker):
    broken = tmp_path / 'broken'
    broken.mkdir()
    if marker == 'file':
        (broken / '.git').write_text('gitdir: /missing/deleted-worktree\n')
    else:
        (broken / '.git').mkdir()
    for n in range(25):
        (broken / f'reading-note-{n}.md').touch()
    valid = tmp_path / 'valid'
    valid.mkdir()
    subprocess.run(['git', 'init', '-q', str(valid)], check=True)
    (valid / 'main.py').touch()
    subprocess.run(['git', '-C', str(valid), 'add', '.'], check=True)
    docs = tmp_path / 'Documents'
    docs.mkdir()
    (docs / 'note.md').touch()
    body = discovery.scan(home=tmp_path, lsblk={}, volume_of=lambda p: ('u', tmp_path),
                          xdg={'DOCUMENTS': docs}, device='cpu').body
    assert [r['path'] for r in body['repos']] == [str(valid)]
    assert body['repos'][0]['tracked'] == 1
    assert body['candidates'][0]['kept'] == 1
    broken_candidate = next(c for c in body['candidates'] if c['path'] == str(broken))
    assert broken_candidate['kept'] == 25 and broken_candidate['git'] is False


def test_scan_shares_all_file_listing_and_preserves_hidden_secrets(tmp_path):
    for folder in ('Documents', 'elsewhere'):
        root = tmp_path / folder
        root.mkdir()
        for n in range(25):
            (root / f'reading-note-{n}.md').touch()
        (root / '.hidden').mkdir()
        (root / '.hidden/secret.md').touch()
        (root / '.hidden/hidden.md').touch()
        (root / 'archive').mkdir()
        for n in range(20):
            (root / f'archive/backup-{n}.zip').touch()
    listings = []

    def run(argv, **kwargs):
        if argv[0] == 'fd' and '-e' not in argv and '-I' not in argv:
            listings.append(argv)
        return subprocess.run(argv, **kwargs)

    scan = discovery.scan(home=tmp_path, lsblk={}, run=run, device='cpu',
                          volume_of=lambda p: ('u', tmp_path),
                          xdg={'DOCUMENTS': tmp_path / 'Documents'})
    assert len(listings) == 1
    assert len(scan.body['candidates']) == 2
    for row in scan.body['candidates']:
        assert row['found'] == 26 and row['kept'] == 25
        assert row['left_out'][-1]['rule'] == 'secrets'
        assert row['left_out'][-1]['files'] == 1
        assert row['left_out'][0]['evidence']['files'] == 20


def test_volume_lookup_reuses_mount_table_and_prefers_inner_mount(monkeypatch):
    from omafindd import store

    calls = []

    def mounted_volumes():
        calls.append(True)
        return {'home-volume': Path('/home'), 'external-volume': Path('/home/u/drive')}

    monkeypatch.setattr(store, 'mounted_volumes', mounted_volumes)
    monkeypatch.setattr(discovery, '_volume_of', lambda p: pytest.fail('per-candidate probe'))
    lookup = discovery._volume_lookup({'blockdevices': [
        {'uuid': 'boot-volume', 'mountpoints': ['/boot']}]})
    assert lookup(Path('/home/u/Documents')) == ('home-volume', Path('/home'))
    assert lookup(Path('/home/u/drive/Documents')) == ('external-volume', Path('/home/u/drive'))
    assert lookup(Path('/boot/docs')) == ('boot-volume', Path('/boot'))
    assert calls == [True]


@pytest.mark.parametrize('overlapping_volume', [False, True])
def test_shared_listing_does_not_duplicate_nested_xdg_or_volume_files(tmp_path, overlapping_volume):
    root = tmp_path / 'Documents'
    nested = root / 'Work'
    nested.mkdir(parents=True)
    for n in range(25):
        (root / f'note-{n}.md').touch()
        (nested / f'note-{n}.md').touch()
    devices = [{'uuid': 'v', 'mountpoints': [str(tmp_path)]}] if overlapping_volume else []
    scan = discovery.scan(home=tmp_path, lsblk={'blockdevices': devices}, device='cpu',
        volume_of=lambda p: ('v', root), xdg={'DOCUMENTS': root, 'WORK': nested})
    rows = {c['path']: c for c in scan.body['candidates']}
    assert rows[str(root)]['found'] == 50
    assert rows[str(nested)]['found'] == 25


def test_repository_counts_keep_the_authoritative_code_classifier(tmp_path):
    from omafindd.code import classify_code

    names = ['main.py', 'notes.md', 'image.png', 'source.ipynb', 'Makefile', 'Dockerfile.dev',
             'LICENSE.py', 'bundle.min.js', '.hidden/main.py', 'vendor/main.py', '.env.py',
             'file.unknown', 'sub/.hidden.md', 'script.SH']
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.touch()
    subprocess.run(['git', '-C', str(tmp_path), 'add', '.'], check=True)
    repo, = discovery._repos([tmp_path], subprocess.run, 'cpu')
    assert repo['tracked'] == len(names)
    assert repo['code_files'] == sum(classify_code(Path(name)) for name in names)
    assert repo['rules'] == ['secrets', 'generated']


def test_scan_ancestor_caches_handle_deep_directories():
    home = Path('/fake-home')
    folder = home.joinpath(*(['a'] * 1200))
    names = [folder / f'reading-note-{n}.md' for n in range(25)]
    payload = b'\0'.join(os.fsencode(p) for p in names) + b'\0'

    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, b'' if '-I' in argv else payload, b'')

    scan = discovery.scan(home=home, lsblk={}, xdg={}, device='cpu', run=run,
                          popen=lambda *a, **kw: Process(names),
                          volume_of=lambda p: ('u', home))
    row, = scan.body['candidates']
    assert row['found'] == row['kept'] == 25
    assert row['dirs'] == 1200
    assert scan.roots[row['path']].dirs[0]['sub']['text'] == 25
