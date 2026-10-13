import random
from pathlib import Path

from omafindd import leftout, rules
from support.documents import documents_files

KINDS = tuple(rules.INDEXED_KINDS)


def test_documents_fixture_ledger():
    files = documents_files()
    proposed = leftout.proposals(files)
    entries = [{'path': 'tax/2024', 'rule': 'user'},
               *sorted(proposed, key=lambda e: leftout.PRECEDENCE.index(e['rule']))]
    result = leftout.ledger(files, entries)
    assert result['found'] == 899
    assert result['kept'] == 793
    assert result['found_counts'] == dict(zip(KINDS, (806, 67, 26, 0, 0), strict=True))
    assert result['counts'] == dict(zip(KINDS, (731, 45, 17, 0, 0), strict=True))
    assert result['dirs'] == 3
    actual = result['left_out']
    assert [(e['path'], e['rule'], e['files']) for e in actual] == [
        ('tax/2024', 'user', 45), ('vault/exports', 'generated', 58),
        ('archive/old-backups', 'no-kind', 0), ('**', 'secrets', 3)]
    assert actual[0]['evidence'] == {'files': 45}
    assert actual[2]['evidence'] == {
        'files': 37, 'exts': [['.zip', 31], ['.tar.gz', 6]], 'searchable': 0}
    assert actual[1]['evidence'] == {
        'pattern': 'inv-YYYYMMDD.txt', 'match': [58, 58], 'dataset_limit': 300}
    assert actual[3]['evidence'] == {
        'exts': [['.env', 3], ['.kdbx', 1]], 'in': ['tax/2024', 'work/clients']}


def test_found_equals_kept_plus_left_out_on_random_trees():
    rng = random.Random(5)
    for _ in range(200):
        files = [leftout.Listed(f'{rng.choice(("a", "a/b", "a/b/c", "d"))}/{n}.md',
                               rng.choice((*KINDS, None)), rng.random() < .2)
                 for n in range(rng.randrange(1, 100))]
        excludes = [{'path': path, 'rule': rng.choice(leftout.PRECEDENCE[1:])}
                    for path in rng.sample(['a', 'a/b', 'a/b/c', 'd'], rng.randrange(5))]
        result = leftout.ledger(files, excludes)
        expected = [dict.fromkeys(KINDS, 0) for _ in range(len(excludes) + 1)]
        kept = dict.fromkeys(KINDS, 0)
        for file in files:
            if file.kind is None:
                continue
            matches = [i for i, e in enumerate(excludes)
                       if file.path.startswith(e['path'] + '/')]
            if file.secret:
                expected[-1][file.kind] += 1
            elif matches:
                i = min(matches, key=lambda i: (
                    leftout.PRECEDENCE.index(excludes[i]['rule']),
                    len(excludes[i]['path'].split('/')), i))
                expected[i][file.kind] += 1
            else:
                kept[file.kind] += 1
        assert result['counts'] == kept
        for i, entry in enumerate(result['left_out'][:len(excludes)]):
            assert entry['counts'] == expected[i]
        for kind in KINDS:
            assert result['found_counts'][kind] == result['counts'][kind] + sum(
                entry['counts'][kind] for entry in result['left_out'])


def test_secret_inside_user_exclude_counts_once():
    result = leftout.ledger([leftout.Listed('a/.env.md', 'text', True)],
                           [{'path': 'a', 'rule': 'user'}])
    assert [e['files'] for e in result['left_out']] == [0, 1]


def test_precedence_user_over_generated_over_no_kind():
    files = [leftout.Listed('a/b/c/x.md', 'text', False)]
    entries = [{'path': 'a', 'rule': 'no-kind'}, {'path': 'a/b', 'rule': 'generated'},
               {'path': 'a/b/c', 'rule': 'user'}]
    assert [e['files'] for e in leftout.ledger(files, entries)['left_out']] == [0, 0, 1]
    entries = [{'path': 'a/b', 'rule': 'user'}, {'path': 'a', 'rule': 'user'}]
    assert [e['files'] for e in leftout.ledger(files, entries)['left_out']] == [0, 1]


def test_58_machine_named_files_are_generated():
    assert next(e for e in leftout.proposals(documents_files()) if e['rule'] == 'generated')[
        'evidence'] == {'pattern': 'inv-YYYYMMDD.txt', 'match': [58, 58], 'dataset_limit': 300}


def test_machine_named_files_in_the_root_itself_are_not_generated():
    files = [leftout.Listed(f'20240518_{n:06}.jpg', 'image', False) for n in range(25)]
    assert leftout.proposals(files) == []


def test_300_machine_named_files_are_a_dataset_skip_not_generated():
    files = [leftout.Listed(f'data/clip_{n:06}.png', 'image', False) for n in range(300)]
    assert rules.datasets([Path(f.path) for f in files], root=Path('.')) == {Path('data')}
    assert leftout.proposals(files) == []


def test_no_kind_entry_reports_searchable_0_and_zero_counts():
    files = [leftout.Listed(f'a/note-{n}.zip', None, False) for n in range(20)]
    result = leftout.ledger(files, leftout.proposals(files))
    entry = result['left_out'][0]
    assert entry['counts'] == dict.fromkeys(KINDS, 0)
    assert entry['evidence']['searchable'] == 0
    assert entry['evidence']['files'] == 20


def test_19_files_no_kind_folder_is_not_proposed():
    assert leftout.proposals([leftout.Listed(f'a/{n}.zip', None, False)
                             for n in range(19)]) == []


def test_extension_matches_path_suffixes_for_unusual_names():
    from pathlib import Path

    from omafindd import leftout

    for name in ('.md', '..md', '...pdf', 'note.', '.tar.gz', '..tar.gz',
                 'a.tar.GZ', 'a.TAR.gz', 'a.tar.gz', 'a..tar.gz'):
        suffixes = Path(name).suffixes
        expected = (''.join(suffixes[-2:]).lower()
                    if len(suffixes) >= 2 and suffixes[-2] == '.tar'
                    else Path(name).suffix.lower())
        assert leftout.extension(name) == expected


def test_deep_directory_exclude_keeps_outermost_precedence():
    from omafindd import leftout

    parent = '/'.join(['a'] * 1200)
    files = [leftout.Listed(parent + '/note.md', 'text', False)]
    result = leftout.ledger(files, [{'path': 'a', 'rule': 'user'},
                                    {'path': parent, 'rule': 'generated', 'evidence': {}}])
    assert result['found'] == 1 and result['kept'] == 0
    assert [entry['files'] for entry in result['left_out']] == [1, 0]
