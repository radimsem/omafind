import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { load } from './load.mjs';
const plain = value => JSON.parse(JSON.stringify(value));

function folders(values = {}) {
  const ctx = vm.createContext({ Tree: load('tree.js'), seeded: true, fromSaved: false, proposed: [], proposedCode: [], discover: null,
    choices: { chosen: [], skipped: [], code: [] },
    service: { worktrees: {}, repos: {}, datasets: { '/h/Photos/data': { path: '/h/Photos/data' } } }, ...values });
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
    { chosen: ['/h/Photos', '/h/Photos/data'], skipped: [], code: [] },
    { chosen: ['/h/Photos'], skipped: ['/h/Photos/data'], code: [] },
  ]) {
    const ctx = folders({ choices });
    ctx.offerDatasets();
    assert.deepEqual(plain(ctx.choices), choices);
  }
});

test('worktrees under a searched folder start unchecked and repos start with code', () => {
  const ctx = folders({
    choices: { chosen: ['/h/p'], skipped: [], code: [] },
    service: { datasets: {}, walks: { '/h': { done: true } },
      worktrees: { '/h/p/wt': { path: '/h/p/wt' } },
      repos: { '/h/p/main': { path: '/h/p/main' } } },
  });
  ctx.offerDatasets();
  ctx.offerRepos();
  assert.deepEqual(plain(ctx.choices.skipped), ['/h/p/wt']);
  assert.deepEqual(plain(ctx.choices.code), ['/h/p/main']);
});

test('repos on a queued drive wait until its covering walk finishes', () => {
  for (const mount of ['/m', '/h/USB']) {
    const ctx = folders({ choices: { chosen: [mount], skipped: [], code: [] },
      discover: { roots: [{ path: '/h' }, { path: mount }] },
      service: { datasets: {}, worktrees: {}, walks: { '/h': { done: true } },
        repos: { [mount + '/data/repo']: { path: mount + '/data/repo' },
          [mount + '/main']: { path: mount + '/main' } } } });
    ctx.offerRepos();
    assert.deepEqual(plain(ctx.choices.code), []);
    ctx.service.walks[mount] = { done: false };
    ctx.offerRepos();
    assert.deepEqual(plain(ctx.choices.code), []);
    ctx.service.datasets = { [mount + '/data']: { path: mount + '/data' } };
    ctx.service.walks[mount] = { done: true };
    ctx.offerDatasets(); ctx.offerRepos();
    assert.deepEqual(plain(ctx.choices.skipped), [mount + '/data']);
    assert.deepEqual(plain(ctx.choices.code), [mount + '/main']);
  }
});

test('repos wait for the walk to reveal dataset exclusions before getting code', () => {
  const ctx = folders({ choices: { chosen: ['/h/p'], skipped: [], code: [] },
    service: { datasets: {}, worktrees: {}, walks: { '/h': { done: false } },
      repos: { '/h/p/data/repo': { path: '/h/p/data/repo' },
        '/h/p/main': { path: '/h/p/main' } } } });
  ctx.offerRepos();
  assert.deepEqual(plain(ctx.choices.code), []);
  ctx.service.datasets = { '/h/p/data': { path: '/h/p/data' } };
  ctx.service.walks = { '/h': { done: true } };
  ctx.offerDatasets(); ctx.offerRepos();
  assert.deepEqual(plain(ctx.choices.skipped), ['/h/p/data']);
  assert.deepEqual(plain(ctx.choices.code), ['/h/p/main']);
});

test('start indexing waits for discovery and saves the automatic Code choices', () => {
  const saved = [];
  const ctx = folders({ discover: {}, roots: [{ path: '/h/p', volume: 'u' }],
    choices: { chosen: ['/h/p'], skipped: [], code: [] },
    service: { scanning: false, datasets: {}, worktrees: {}, walks: { '/h': { done: false } },
      repos: { '/h/p/main': { path: '/h/p/main' } },
      startIndexing(roots, code) { saved.push(plain({ roots, code })); } } });
  ctx.startIndexing();
  assert.deepEqual(saved, []);
  assert.equal(ctx.ready, false);
  ctx.service.walks = { '/h': { done: true } };
  ctx.offerDatasets(); ctx.offerRepos();
  assert.equal(ctx.ready, true);
  ctx.startIndexing();
  assert.deepEqual(saved, [{ roots: [{ path: '/h/p', volume: 'u' }], code: [{ path: '/h/p/main', excludes: [] }] }]);
});

test('start indexing saves code only for searched repos', () => {
  const saved = [];
  const ctx = folders({ discover: {}, roots: [{ path: '/h/p', volume: 'u' }],
    choices: { chosen: ['/h/p'], skipped: ['/h/p/off', '/h/p/main/docs'],
      code: ['/h/p/main', '/h/p/off/repo', '/h/x'] },
    service: { scanning: false, datasets: {}, worktrees: {}, walks: { '/h': { done: true } }, repos: {},
      startIndexing(roots, code) { saved.push(plain(code)); } } });
  ctx.startIndexing();
  assert.deepEqual(saved, [[{ path: '/h/p/main', excludes: ['docs'] }]]);
});

test('a finished setup reopens on the saved folders and keeps its worktree and code choices', () => {
  const ctx = folders({ seeded: false, discover: { folders: [{ path: '/h/Docs', xdg: true }] },
    service: { settings: { setupDone: true,
      roots: [{ path: '/h/p', volume: 'u', excludes: ['skip'] }],
      codeRoots: [{ path: '/h/p/main', excludes: ['docs'] }] },
    datasets: {}, walks: { '/h': { done: true } },
    worktrees: { '/h/p/wt': { path: '/h/p/wt' } },
    repos: { '/h/p/main': { path: '/h/p/main' }, '/h/p/other': { path: '/h/p/other' } } } });
  ctx.seed();
  assert.deepEqual(plain(ctx.choices), { chosen: ['/h/p'], skipped: ['/h/p/skip', '/h/p/main/docs'],
    code: ['/h/p/main'] });
  ctx.service.worktrees['/h/p/later'] = { path: '/h/p/later' };
  ctx.offerDatasets(); ctx.offerRepos();
  assert.deepEqual(plain(ctx.choices.skipped), ['/h/p/skip', '/h/p/main/docs']);
  assert.deepEqual(plain(ctx.choices.code), ['/h/p/main']);
});

test('a setup that is not finished starts from the XDG folders', () => {
  const ctx = folders({ seeded: false, discover: { folders: [{ path: '/h/Docs', xdg: true }] },
    service: { settings: { setupDone: false, roots: [{ path: '/h/p', volume: 'u', excludes: [] }], codeRoots: [] },
      datasets: {}, worktrees: {}, repos: {}, walks: {} } });
  ctx.seed();
  assert.deepEqual(plain(ctx.choices), { chosen: ['/h/Docs'], skipped: [], code: [] });
});
