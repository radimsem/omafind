import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import vm from 'node:vm';
import { load } from './load.mjs';

function tree(values = {}) {
  const items = [];
  const model = {
    get count() { return items.length; }, get: i => items[i],
    append: row => items.push(row), insert: (i, row) => items.splice(i, 0, row),
    remove: (i, n) => items.splice(i, n), clear: () => items.splice(0),
  };
  const ctx = vm.createContext({ Tree: load('tree.js'), Setup: load('setup.js'),
    finished: {}, folders: [], mounts: [], meta: {}, expanded: {}, counts: {}, walks: {}, datasets: {}, cached: {},
    rows: model, service: null, home: '/h', mount: '', ...values });
  ctx.root = ctx;
  const file = new URL('../../ui/FolderTree.qml', import.meta.url);
  const source = existsSync(file) ? readFileSync(file, 'utf8') : '';
  for (const match of source.matchAll(/^  function \w+\([^]*?^  \}/gm)) vm.runInContext(match[0], ctx);
  const walkHandler = source.match(/^  onWalksChanged: \{([^]*?)^  \}/m);
  if (walkHandler) vm.runInContext('function walksChanged() {' + walkHandler[1] + '}', ctx);
  const totals = source.match(/readonly property var totals: \{([^]*?)^  \}/m);
  if (totals) vm.runInContext('function calculatedTotals() {' + totals[1] + '}', ctx);
  return ctx;
}
const folder = path => ({ path, name: path.split('/').at(-1), hasChildren: true });
const paths = ctx => Array.from({ length: ctx.rows.count }, (_, i) => ctx.rows.get(i).path);

test('expand requests one level and collapse retains cached descendants', () => {
  let asks = 0;
  const ctx = tree({ folders: [folder('/h/a')], service: { requestChildren() { asks++; } } });
  ctx.reload(); ctx.toggle(0);
  assert.equal(asks, 1);
  assert.deepEqual(paths(ctx), ['/h/a']);
  ctx.cached['/h/a'] = { dirs: [folder('/h/a/b')] };
  ctx.insert(0, '/h/a', 0);
  ctx.cached['/h/a/b'] = { dirs: [folder('/h/a/b/c')] };
  ctx.toggle(1);
  assert.deepEqual(paths(ctx), ['/h/a', '/h/a/b', '/h/a/b/c']);
  ctx.toggle(0); ctx.toggle(0);
  assert.deepEqual(paths(ctx), ['/h/a', '/h/a/b', '/h/a/b/c']);
  assert.equal(asks, 1);
});

test('missing counts wait while running and become zero when a walk ends or fails', () => {
  const ctx = tree({ walks: { '/h': { done: false } } });
  assert.equal(ctx.countOf('/h/a'), null);
  ctx.walks['/h'] = { done: true, error: 'fd failed' };
  assert.equal(ctx.countOf('/h/a').text, 0);
  assert.equal(ctx.countOf('/other'), null);
  assert.equal(ctx.label(folder('/h/a'), 0), '~/a');
  assert.equal(ctx.label(folder('/h/a/b'), 1), 'b');
});

test('reopening an unreadable folder retries the children request', () => {
  let asks = 0;
  const ctx = tree({ folders: [folder('/h/a')],
    cached: { '/h/a': { dirs: [], error: 'Permission denied' } },
    service: { requestChildren() { asks++; } } });
  ctx.reload(); ctx.toggle(0);
  assert.equal(asks, 1);
});


test('overlapping top rows count selected files only once', () => {
  const ctx = tree({ folders: [folder('/h/Docs'), folder('/h')],
    choices: { chosen: ['/h'], skipped: [] },
    counts: { '/h': { text: 3 }, '/h/Docs': { text: 3 } }, rates: null, device: 'gpu' });
  assert.equal(ctx.calculatedTotals().files, 3);
});

test('cached child metadata cannot revive counts cleared by a fresh walk', () => {
  const ctx = tree({ walks: { '/h': { done: false } },
    meta: { '/h/Docs': { counts: { text: 9 } } } });
  assert.equal(ctx.countOf('/h/Docs'), null);
});


test('adding folders or refreshing top rows retains expansions that still exist', () => {
  const ctx = tree({ folders: [folder('/h/a'), folder('/h/gone')],
    cached: { '/h/a': { dirs: [folder('/h/a/b')] }, '/h/a/b': { dirs: [folder('/h/a/b/c')] } } });
  ctx.reload(); ctx.toggle(0); ctx.toggle(1); ctx.toggle(3);
  ctx.folders = [folder('/h/a'), folder('/outside')];
  ctx.reload();
  assert.deepEqual(paths(ctx), ['/h/a', '/h/a/b', '/h/a/b/c', '/outside']);
  assert.equal(ctx.expanded['/h/a'], true);
  assert.equal(ctx.expanded['/h/a/b'], true);
  assert.equal(ctx.expanded['/h/gone'], undefined);
});

test('refreshing expanded folders requests children again when their cache was cleared', () => {
  let asks = 0;
  const ctx = tree({ folders: [folder('/h/a')], cached: { '/h/a': { dirs: [folder('/h/a/b')] } },
    service: { requestChildren() { asks++; } } });
  ctx.reload(); ctx.toggle(0);
  ctx.cached = {}; ctx.reload();
  assert.equal(ctx.expanded['/h/a'], true);
  assert.equal(asks, 1);
});

test('a children reply inserts its rows without rebuilding the list', () => {
  const ctx = tree({ folders: [folder('/h/a'), folder('/h/z')], service: { requestChildren() {} } });
  ctx.reload(); ctx.toggle(0);
  const kept = ctx.rows.get(1);
  ctx.cached = { '/h/a': { dirs: [folder('/h/a/b')] } };
  const source = readFileSync(new URL('../../ui/FolderTree.qml', import.meta.url), 'utf8');
  const handler = source.match(/^  onCachedChanged: (.*)$/m);
  assert.ok(handler, 'onCachedChanged handler');
  vm.runInContext('function cacheChanged() {' + handler[1] + '}', ctx);
  ctx.cacheChanged(); ctx.cacheChanged();
  assert.deepEqual(paths(ctx), ['/h/a', '/h/a/b', '/h/z']);
  assert.equal(ctx.rows.get(2), kept);
});

test('cache reloads retain errors without retrying expanded unreadable folders', () => {
  const asks = [];
  const ctx = tree({ folders: [folder('/h/a'), folder('/h/b')],
    expanded: { '/h/a': true, '/h/b': true },
    cached: { '/h/a': { dirs: [], error: 'Permission denied' },
      '/h/b': { dirs: [], error: 'Permission denied' } },
    service: { requestChildren(path) { asks.push(path); } } });
  ctx.reload(); ctx.reload();
  assert.deepEqual(asks, []);
  ctx.toggle(0); ctx.toggle(0);
  assert.deepEqual(asks, ['/h/a']);
});

test('cached errors in expanded descendants wait for an explicit retry', () => {
  const asks = [];
  const ctx = tree({ folders: [folder('/h/a')], expanded: { '/h/a': true, '/h/a/b': true },
    cached: { '/h/a': { dirs: [folder('/h/a/b')] },
      '/h/a/b': { dirs: [], error: 'Permission denied' } },
    service: { requestChildren(path) { asks.push(path); } } });
  ctx.reload();
  assert.deepEqual(paths(ctx), ['/h/a', '/h/a/b']);
  assert.deepEqual(asks, []);
  ctx.toggle(1); ctx.toggle(1);
  assert.deepEqual(asks, ['/h/a/b']);
});


test('a finished walk sorts each open level once and keeps focus and expansion by path', () => {
  let focused = '/h/a/b', positioned = [];
  const ctx = tree({ folders: [folder('/h/a'), folder('/h/z')],
    expanded: { '/h/a': true }, cached: { '/h/a': { dirs: [folder('/h/a/b'), folder('/h/a/c')] } },
    walks: { '/h': { done: false } },
    list: { itemAtIndex(index) { return { holdsFocus: ctx.rows.get(index)?.path === focused,
      focusCheck() { focused = ctx.rows.get(index).path; } }; },
    positionViewAtIndex(index) { positioned.push(index); } }, ListView: { Contain: 1 } });
  ctx.reload();
  ctx.counts = { '/h/z': { text: 10 }, '/h/a': { text: 5 }, '/h/a/c': { text: 4 }, '/h/a/b': { text: 1 } };
  const before = ctx.rows.get(0);
  ctx.walksChanged();
  assert.equal(ctx.rows.get(0), before);
  ctx.walks = { '/h': { done: true } };
  ctx.walksChanged();
  assert.deepEqual(paths(ctx), ['/h/z', '/h/a', '/h/a/c', '/h/a/b']);
  assert.equal(focused, '/h/a/b');
  assert.equal(ctx.expanded['/h/a'], true);
  const sorted = ctx.rows.get(0);
  ctx.walksChanged();
  assert.equal(ctx.rows.get(0), sorted);
  assert.deepEqual(positioned, [3]);
});

test('a rescan sorts again when the same root finishes', () => {
  const ctx = tree({ folders: [folder('/h/a'), folder('/h/b')], walks: { '/h': { done: true } },
    counts: { '/h/a': { text: 3 }, '/h/b': { text: 1 } },
    list: { itemAtIndex() { return null; } } });
  ctx.reload(); ctx.walksChanged();
  ctx.walks = { '/h': { done: false } }; ctx.walksChanged();
  ctx.counts = { '/h/a': { text: 1 }, '/h/b': { text: 5 } };
  ctx.walks = { '/h': { done: true } }; ctx.walksChanged();
  assert.deepEqual(paths(ctx), ['/h/b', '/h/a']);
});

test('a rescan that drops the walk sorts again when the root finishes', () => {
  const ctx = tree({ folders: [folder('/h/a'), folder('/h/b')], walks: { '/h': { done: true } },
    counts: { '/h/a': { text: 3 }, '/h/b': { text: 1 } },
    list: { itemAtIndex() { return null; } } });
  ctx.reload(); ctx.walksChanged();
  ctx.walks = {}; ctx.walksChanged();
  ctx.counts = { '/h/a': { text: 1 }, '/h/b': { text: 5 } };
  ctx.walks = { '/h': { done: true } }; ctx.walksChanged();
  assert.deepEqual(paths(ctx), ['/h/b', '/h/a']);
});

test('a row click leaves the known worktrees and datasets below it out', () => {
  const edits = [];
  const ctx = tree({ choices: { chosen: [], skipped: [] },
    service: { worktrees: { '/h/p/wt': { path: '/h/p/wt' } },
      datasets: { '/h/p/frames': { path: '/h/p/frames' } } },
    choicesEdited: next => edits.push(JSON.parse(JSON.stringify(next))) });
  ctx.clickRow('/h/p');
  assert.deepEqual(edits, [{ chosen: ['/h/p'], skipped: ['/h/p/wt', '/h/p/frames'] }]);
});
