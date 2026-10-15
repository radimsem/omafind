import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
import { plain, freeze } from './fixtures.mjs';
const t = load('tree.js');
const state = (chosen, skipped = [], code = []) => freeze({ chosen, skipped, code });
const ZERO = { text: 0, pdf: 0, image: 0, video: 0, audio: 0 };
const c = (text, image = 0) => ({ ...ZERO, text, image });

test('the nearest choice decides whether a folder is searched', () => {
  const s = state(['/h/Docs', '/h/Docs/a/b'], ['/h/Docs/a']);
  assert.equal(t.searched('/h/Docs/x', s), true);
  assert.equal(t.searched('/h/Docs/a/c', s), false);
  assert.equal(t.searched('/h/Docs/a/b/deep', s), true);
  assert.equal(t.searched('/h/Pictures', s), false);
  assert.equal(t.searched('/h/Docsx', s), false);
});

test('marks compare choices at any depth below a folder', () => {
  const s = state(['/h/Docs'], ['/h/Docs/a/b/c']);
  assert.equal(t.mark('/h/Docs', s), 'mixed');
  assert.equal(t.mark('/h/Docs/a', s), 'mixed');
  assert.equal(t.mark('/h/Docs/a/b/c', s), 'off');
  assert.equal(t.mark('/h/Docs/z', s), 'on');
  assert.equal(t.mark('/h/Docs/new/child', state(['/h/Docs'])), 'on');
  assert.equal(t.mark('/h', s), 'mixed');
  assert.equal(t.mark('/h/Pictures', s), 'off');
});

test('a click sets the folder and clears every choice below it', () => {
  const s = state(['/h/Docs', '/h/Docs/a/b'], ['/h/Docs/a', '/h/Docs/x']);
  const whole = t.click(s, '/h/Docs');
  assert.deepEqual(plain(whole), { chosen: ['/h/Docs'], skipped: [], code: [] });
  assert.deepEqual(plain(t.click(whole, '/h/Docs')), { chosen: [], skipped: [], code: [] });
  const child = t.click(state(['/h/Docs']), '/h/Docs/a');
  assert.deepEqual(plain(child), { chosen: ['/h/Docs'], skipped: ['/h/Docs/a'], code: [] });
  assert.deepEqual(plain(t.click(child, '/h/Docs/a')), { chosen: ['/h/Docs'], skipped: [], code: [] });
  assert.deepEqual(plain(t.click(state([], ['/h/Docs/a']), '/h/Docs/a/b')),
    { chosen: ['/h/Docs/a/b'], skipped: ['/h/Docs/a'], code: [] });
});

test('XDG folders start chosen and datasets start skipped under a searched parent', () => {
  const s = t.initial(freeze([{ path: '/h/Docs', xdg: true }, { path: '/h/code', xdg: false }]));
  assert.deepEqual(plain(s), { chosen: ['/h/Docs'], skipped: [], code: [] });
  const next = t.addDatasets(s, freeze([{ path: '/h/Docs/frames' }, { path: '/h/code/frames' },
    { path: '/h/Docs/kept' }]), ['/h/Docs/kept']);
  assert.deepEqual(plain(next.skipped), ['/h/Docs/frames']);
  assert.equal(t.mark('/h/Docs', next), 'mixed');
  const chosenSet = t.click(next, '/h/Docs/frames');
  assert.deepEqual(plain(t.addDatasets(chosenSet, [{ path: '/h/Docs/frames' }], ['/h/Docs/frames']).skipped), []);
});

test('value counts searched files from rolled-up counts and waits for missing ones', () => {
  const counts = { '/h/Docs': c(10, 5), '/h/Docs/a': c(4, 5), '/h/Docs/a/b': c(1, 0) };
  const countOf = path => counts[path] || null;
  const s = state(['/h/Docs', '/h/Docs/a/b'], ['/h/Docs/a']);
  assert.deepEqual(plain(t.value('/h/Docs', s, countOf)), c(7, 0));
  assert.deepEqual(plain(t.value('/h/Docs/a', s, countOf)), c(1, 0));
  assert.deepEqual(plain(t.value('/h/Pictures', s, () => c(3))), ZERO);
  assert.equal(t.value('/h/Docs', s, path => path === '/h/Docs/a/b' ? null : counts[path]), null);
  assert.equal(t.value('/h/Docs', state(['/h/Docs']), () => null), null);
});

test('the code toggle keeps its own set through clicks', () => {
  const s = t.toggleCode(state(['/h/Docs']), '/h/omaone');
  assert.deepEqual(plain(s.code), ['/h/omaone']);
  assert.deepEqual(plain(t.toggleCode(s, '/h/omaone').code), []);
  assert.deepEqual(plain(t.click(s, '/h/omaone').code), ['/h/omaone']);
});

test('toRoots turns the sets into roots with relative excludes', () => {
  const s = state(['/h/Docs', '/h/Docs/a/b'], ['/h/Docs/a']);
  assert.deepEqual(plain(t.toRoots(s.chosen, s.skipped, () => 'u')), [
    { path: '/h/Docs', volume: 'u', excludes: ['a'] },
    { path: '/h/Docs/a/b', volume: 'u', excludes: [] }]);
  assert.deepEqual(plain(t.toRoots(['/', '/a'], ['/b'], () => 'v')),
    [{ path: '/', volume: 'v', excludes: ['b'] }]);
});

test('a drive mounted below a searched folder is its own root and adds to its parent', () => {
  // The /h walk stays on its filesystem, so /h/Media never counts the files of /h/Media/USB.
  const counts = { '/h/Media': c(2), '/h/Media/USB': c(5), '/h/Media/USB/junk': c(1) };
  const countOf = path => counts[path] || null;
  const mounts = ['/h/Media/USB'];
  const on = state(['/h/Media'], ['/h/Media/USB/junk']);
  assert.deepEqual(plain(t.value('/h/Media', on, countOf, mounts)), c(6));
  assert.deepEqual(plain(t.toRoots(on.chosen, on.skipped, path => path.includes('USB') ? 'usb' : 'u', mounts)), [
    { path: '/h/Media', volume: 'u', excludes: ['USB/junk'] },
    { path: '/h/Media/USB', volume: 'usb', excludes: ['junk'] }]);
  const off = state(['/h/Media'], ['/h/Media/USB']);
  assert.deepEqual(plain(t.value('/h/Media', off, countOf, mounts)), c(2));
  assert.deepEqual(plain(t.toRoots(off.chosen, off.skipped, () => 'u', mounts)),
    [{ path: '/h/Media', volume: 'u', excludes: ['USB'] }]);
});

test('rows sort by known total, then unknown, then zero, then name', () => {
  const Tree = load('tree.js');
  const counts = { '/h/a': { text: 1, pdf: 0, image: 0, video: 0, audio: 0 },
    '/h/b': { text: 0, pdf: 0, image: 9, video: 0, audio: 0 },
    '/h/z': { text: 0, pdf: 0, image: 0, video: 0, audio: 0 } };
  const rows = ['/h/z', '/h/Unknown', '/h/a', '/h/b', '/h/c'].map(path => (
    { path, name: path.slice(3) }));
  const sorted = Tree.byCount(rows, path => counts[path] || null);
  assert.deepEqual(plain(sorted.map(row => row.path)), ['/h/b', '/h/a', '/h/c', '/h/Unknown', '/h/z']);
});

test('repos inside skipped folders or worktrees are not offered code', () => {
  const Tree = load('tree.js');
  const state = { chosen: ['/h/p'], skipped: ['/h/p/skip'], code: [] };
  const repos = [{ path: '/h/p/a' }, { path: '/h/p/skip/b' }, { path: '/h/p/wt/c' },
    { path: '/h/other/d' }];
  const next = Tree.addCode(state, repos, [], ['/h/p/wt']);
  assert.deepEqual(plain(next.code), ['/h/p/a']);
  assert.deepEqual(plain(Tree.addCode(Tree.toggleCode(next, '/h/p/a'), repos, ['/h/p/a'], ['/h/p/wt']).code), []);
});
