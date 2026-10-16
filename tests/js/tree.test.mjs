import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
import { plain, freeze } from './fixtures.mjs';
const t = load('tree.js');
const state = (chosen, skipped = [], code = []) => freeze({ chosen, skipped, code });
const ZERO = { text: 0, pdf: 0, image: 0, video: 0, audio: 0, code: 0 };
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

test('a parent click keeps known worktrees and datasets below it left out', () => {
  const defaults = ['/h/personal/projects/aside-11', '/h/personal/frames'];
  const on = t.click(state(['/h/Documents']), '/h/personal', defaults);
  assert.deepEqual(plain(on), { chosen: ['/h/Documents', '/h/personal'],
    skipped: ['/h/personal/frames', '/h/personal/projects/aside-11'], code: [] });
  assert.equal(t.mark('/h/personal', on), 'mixed');
  // The parent is mixed only through the defaults, so the next click turns it off.
  const off = t.click(on, '/h/personal', defaults);
  assert.deepEqual(plain(off), { chosen: ['/h/Documents'], skipped: [], code: [] });
  assert.deepEqual(plain(t.click(off, '/h/personal', defaults)), plain(on));
});

test('a parent click over a user skip searches the parent without its worktrees', () => {
  const defaults = ['/h/p/wt'];
  const s = state(['/h/p'], ['/h/p/wt', '/h/p/junk']);
  assert.deepEqual(plain(t.click(s, '/h/p', defaults)), { chosen: ['/h/p'], skipped: ['/h/p/wt'], code: [] });
});

test('ticking a worktree row itself still searches it', () => {
  const defaults = ['/h/p/wt'];
  const s = state(['/h/p'], ['/h/p/wt']);
  assert.deepEqual(plain(t.click(s, '/h/p/wt', defaults)), { chosen: ['/h/p'], skipped: [], code: [] });
  const nested = t.click(state([]), '/h/p/wt', ['/h/p/wt', '/h/p/wt/frames']);
  assert.deepEqual(plain(nested), { chosen: ['/h/p/wt'], skipped: ['/h/p/wt/frames'], code: [] });
});

test('a click that leaves a repo unsearched drops its code', () => {
  const s = state(['/h/p'], [], ['/h/p/a', '/h/p/b', '/h/other']);
  assert.deepEqual(plain(t.click(s, '/h/p').code), ['/h/other']);
  assert.deepEqual(plain(t.click(s, '/h/p/a').code), ['/h/p/b', '/h/other']);
  assert.deepEqual(plain(t.click(s, '/h/p/a/docs').code), ['/h/p/a', '/h/p/b', '/h/other']);
});

test('value counts code files only under searched repos whose code is on', () => {
  const cc = (text, code) => ({ ...ZERO, text, code });
  const counts = { '/h/p': cc(10, 50), '/h/p/a': cc(4, 30), '/h/p/a/docs': cc(1, 5),
    '/h/p/a/sub': cc(0, 8), '/h/p/b': cc(2, 20) };
  const countOf = path => counts[path] || null;
  const repos = ['/h/p/a', '/h/p/a/sub', '/h/p/b'];
  const on = state(['/h/p'], [], ['/h/p/a']);
  assert.deepEqual(plain(t.value('/h/p', on, countOf, [], repos)), cc(10, 22));
  assert.deepEqual(plain(t.value('/h/p/a', on, countOf, [], repos)), cc(4, 22));
  assert.deepEqual(plain(t.value('/h/p/b', on, countOf, [], repos)), cc(2, 0));
  const skipped = state(['/h/p'], ['/h/p/a/docs'], ['/h/p/a', '/h/p/a/sub']);
  assert.deepEqual(plain(t.value('/h/p', skipped, countOf, [], repos)), cc(9, 25));
  assert.deepEqual(plain(t.value('/h/p', state([], [], ['/h/p/a']), countOf, [], repos)), cc(0, 0));
});

test('a folder ticked again inside a skipped part of a repo counts no code', () => {
  const cc = (text, code) => ({ ...ZERO, text, code });
  const counts = { '/h/p': cc(10, 50), '/h/p/a': cc(4, 30), '/h/p/a/docs': cc(1, 5),
    '/h/p/a/docs/keep': cc(1, 3), '/h/p/a/sub': cc(0, 8) };
  const countOf = path => counts[path] || null;
  const repos = ['/h/p/a', '/h/p/a/sub'];
  const s = state(['/h/p', '/h/p/a/docs/keep'], ['/h/p/a/docs'], ['/h/p/a']);
  assert.equal(t.codeOn('/h/p/a/docs/keep', s, repos), false);
  assert.deepEqual(plain(t.value('/h/p/a/docs/keep', s, countOf, [], repos)), cc(1, 0));
  assert.deepEqual(plain(t.value('/h/p', s, countOf, [], repos)), cc(10, 17));
});

test('code roots carry the skipped folders below each repo as relative excludes', () => {
  assert.deepEqual(plain(t.toCodeRoots(['/h/p/a', '/h/p/b'], ['/h/p/a/docs', '/h/p/a/x/y', '/h/p/c', '/h/p/a'])), [
    { path: '/h/p/a', excludes: ['docs', 'x/y'] }, { path: '/h/p/b', excludes: [] }]);
});

test('saved roots and code roots turn back into choices', () => {
  const next = t.fromSettings(freeze([{ path: '/h/p', volume: 'u', excludes: ['wt', 'a/b', '/h/p/abs'] },
    { path: '/h/Docs', volume: 'u', excludes: [] }]),
  freeze([{ path: '/h/p/main', excludes: ['docs'] }, { path: '/h/p/old', excludes: [] }]));
  assert.deepEqual(plain(next), { chosen: ['/h/p', '/h/Docs'],
    skipped: ['/h/p/wt', '/h/p/a/b', '/h/p/abs', '/h/p/main/docs'], code: ['/h/p/main', '/h/p/old'] });
});
