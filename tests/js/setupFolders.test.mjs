import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { load } from './load.mjs';
const plain = value => JSON.parse(JSON.stringify(value));

function folders(values = {}) {
  const ctx = vm.createContext({ Tree: load('tree.js'), seeded: true, fromSaved: false, proposed: [], discover: null,
    choices: { chosen: [], skipped: [] },
    service: { discovery: { worktrees: {}, datasets: { '/h/Photos/data': { path: '/h/Photos/data' } } } }, ...values });
  ctx.root = ctx;
  const source = readFileSync(new URL('../../ui/SetupFolders.qml', import.meta.url), 'utf8');
  for (const match of source.matchAll(/^  function \w+\([^]*?^  \}/gm)) vm.runInContext(match[0], ctx);
  const handler = source.match(/^  onChoicesChanged: (.*)$/m);
  vm.runInContext('function choicesChanged() {' + (handler ? handler[1] : '') + '}', ctx);
  const ready = source.match(/readonly property bool ready: ([^]*?)\n\n/);
  Object.defineProperty(ctx, 'ready', { get: () => vm.runInContext(ready[1], ctx) });
  return ctx;
}

test('datasets seen under an unchecked parent are offered when the parent is checked', () => {
  const ctx = folders();
  ctx.offerDatasets();
  assert.deepEqual(plain(ctx.proposed), []);
  ctx.choices = ctx.Tree.click(ctx.choices, '/h/Photos');
  ctx.choicesChanged();
  assert.deepEqual(plain(ctx.choices.skipped), ['/h/Photos/data']);
  assert.deepEqual(plain(ctx.proposed), ['/h/Photos/data']);
  ctx.choices = ctx.Tree.click(ctx.choices, '/h/Photos/data');
  ctx.choicesChanged(); ctx.offerDatasets();
  assert.deepEqual(plain(ctx.choices.skipped), []);
});

test('explicit dataset choices are never replaced by a proposal', () => {
  for (const choices of [
    { chosen: ['/h/Photos', '/h/Photos/data'], skipped: [] },
    { chosen: ['/h/Photos'], skipped: ['/h/Photos/data'] },
  ]) {
    const ctx = folders({ choices });
    ctx.offerDatasets();
    assert.deepEqual(plain(ctx.choices), choices);
  }
});

test('worktrees under a searched folder start unchecked', () => {
  const ctx = folders({
    choices: { chosen: ['/h/p'], skipped: [] },
    service: { discovery: { datasets: {}, walks: { '/h': { done: true } },
      worktrees: { '/h/p/wt': { path: '/h/p/wt' } } } },
  });
  ctx.offerDatasets();
  assert.deepEqual(plain(ctx.choices.skipped), ['/h/p/wt']);
});

test('start indexing waits for discovery and the walks, then saves the roots', () => {
  const saved = [];
  const ctx = folders({ discover: {}, roots: [{ path: '/h/p', volume: 'u' }],
    choices: { chosen: ['/h/p'], skipped: [] },
    service: { discovery: { scanning: false, datasets: {}, worktrees: {}, walks: { '/h': { done: false } } },
      startIndexing(...args) { saved.push(plain(args)); } } });
  ctx.startIndexing();
  assert.deepEqual(saved, []);
  assert.equal(ctx.ready, false);
  ctx.service.discovery.walks = { '/h': { done: true } };
  assert.equal(ctx.ready, true);
  ctx.startIndexing();
  assert.deepEqual(saved, [[[{ path: '/h/p', volume: 'u' }]]]);
});

test('a finished setup reopens on the saved folders and keeps its worktree choices', () => {
  const ctx = folders({ seeded: false, discover: { folders: [{ path: '/h/Docs', xdg: true }] },
    service: { settings: { setupDone: true,
      roots: [{ path: '/h/p', volume: 'u', excludes: ['skip'] }] },
    discovery: { datasets: {}, walks: { '/h': { done: true } },
      worktrees: { '/h/p/wt': { path: '/h/p/wt' } } } } });
  ctx.seed();
  assert.deepEqual(plain(ctx.choices), { chosen: ['/h/p'], skipped: ['/h/p/skip'] });
  ctx.service.discovery.worktrees['/h/p/later'] = { path: '/h/p/later' };
  ctx.offerDatasets();
  assert.deepEqual(plain(ctx.choices.skipped), ['/h/p/skip']);
});

test('a setup that is not finished starts from the XDG folders', () => {
  const ctx = folders({ seeded: false, discover: { folders: [{ path: '/h/Docs', xdg: true }] },
    service: { settings: { setupDone: false, roots: [{ path: '/h/p', volume: 'u', excludes: [] }] },
      discovery: { datasets: {}, worktrees: {}, walks: {} } } });
  ctx.seed();
  assert.deepEqual(plain(ctx.choices), { chosen: ['/h/Docs'], skipped: [] });
});
