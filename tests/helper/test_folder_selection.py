from pathlib import Path

from omafindd.selection import FolderSelection, to_roots


def test_unchecking_a_subfolder_skips_it():
    s = FolderSelection(chosen=['/D'])
    s.set_subfolder('/D/Courses', False)
    assert s.skipped == ['/D/Courses'] and s.mark('/D') == 'mixed'
    assert not s.is_searched('/D/Courses/week1.mp4')
    assert s.is_searched('/D/Books/a.pdf')
    s.set_folder('/D', True)
    assert s.skipped == [] and s.mark('/D') == 'on'


def test_checking_a_subfolder_chooses_it_alone():
    s = FolderSelection()
    s.set_subfolder('/D/Receipts', True)
    assert s.chosen == ['/D/Receipts'] and s.mark('/D') == 'mixed'
    assert s.is_searched('/D/Receipts/may.pdf') and not s.is_searched('/D/other.pdf')
    assert s.folders == ['/D/Receipts']
    s.set_folder('/D', True)
    assert s.chosen == ['/D']
    s.set_folder('/D', False)
    assert s.chosen == [] and s.mark('/D') == 'off'


def test_unchecking_a_folder_drops_its_subfolder_choices_but_not_deeper_skips():
    s = FolderSelection(chosen=['/D'], skipped=['/D/A', '/D/B/old'])
    s.set_folder('/D', False)
    assert s.chosen == [] and s.skipped == ['/D/B/old'] and s.effective_skips == []


def test_a_chosen_folder_inside_a_skipped_one_is_searched_whole():
    s = FolderSelection(chosen=['/D'], skipped=['/D/Media'])
    s.set_subfolder('/D/Media/Courses', True)
    assert s.chosen == ['/D', '/D/Media/Courses']
    assert s.is_searched('/D/Media/Courses/week1/a.mp4')
    assert not s.is_searched('/D/Media/film.mp4')
    assert s.folders == ['/D', '/D/Media/Courses']
    s.set_subfolder('/D/Media/Courses/old', False)
    assert not s.is_searched('/D/Media/Courses/old/b.mp4')


def test_folders_inside_another_chosen_one_are_covered():
    s = FolderSelection(chosen=['/D/A', '/D', '/E', '/D'])
    assert s.folders == ['/D', '/E']
    assert s.searched_as('/D/A/x.png') == '/D/A'
    assert s.searched_as('/outside') is None


def test_kept_folders_stay_whatever_is_clicked():
    s = FolderSelection(kept=['/D/Receipts'])
    assert s.mark('/D') == 'mixed'
    s.set_folder('/D', True)
    assert s.folders == ['/D']
    s.set_folder('/D', False)
    assert s.folders == ['/D/Receipts'] and s.mark('/D') == 'mixed'


def test_checking_a_skipped_folder_takes_the_skip_back():
    s = FolderSelection(skipped=['/H/Movies'], kept=['/H'])
    assert not s.is_searched('/H/Movies')
    s.set_folder('/H/Movies', True)
    assert s.skipped == [] and s.chosen == []
    s.set_folder('/H/Movies', False)
    assert s.skipped == ['/H/Movies']
    s.unskip('/H/Movies')
    assert s.effective_skips == []


def test_paths_are_compared_by_whole_names():
    assert not FolderSelection.is_inside('/a/bc', '/a/b')
    assert FolderSelection.is_inside('/a/b/c', '/a/b')
    assert not FolderSelection(chosen=['/a/b']).is_searched('/a/bc/x')


def test_to_roots_makes_excludes_relative_and_splits_chosen_inside_skipped():
    s = FolderSelection(chosen=['/D', '/D/Media/Courses'],
                        skipped=['/D/Media', '/D/Media/Courses/old'])
    assert to_roots(s, lambda path: ('u', Path('/'))) == [
        {'path': '/D', 'volume': 'u', 'excludes': ['Media', 'Media/Courses/old']},
        {'path': '/D/Media/Courses', 'volume': 'u', 'excludes': ['old']}]
