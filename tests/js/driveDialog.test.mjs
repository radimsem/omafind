import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { load } from './load.mjs';
const plain = value => JSON.parse(JSON.stringify(value));
function dialog(values = {}) {
  const ctx = vm.createContext({ Tree: load('tree.js'), Setup: load('setup.js'),
    folders: [], choices: { chosen: [], skipped: [], code: [] }, proposed: [], seeded: false,
    uuid: 'usb', mount: '/m', phase: 'pick', sawProgress: false, ...values });
  ctx.root = ctx;
  const source = readFileSync(new URL('../../ui/DriveDialog.qml', import.meta.url), 'utf8');
  for (const match of source.matchAll(/^  function \w+\([^]*?^  \}/gm)) vm.runInContext(match[0], ctx);
  return ctx;
}

test('drive folders start checked and dataset proposals preserve user edits', () => {
  const ctx = dialog({ folders: [{ path: '/m/Photos' }],
    service: { datasets: { '/m/Photos/frames': { path: '/m/Photos/frames' } } } });
  ctx.seed();
  assert.deepEqual(plain(ctx.choices), { chosen: ['/m/Photos'], skipped: ['/m/Photos/frames'], code: [] });
  ctx.choices = ctx.Tree.click(ctx.choices, '/m/Photos/frames');
  ctx.offerDatasets();
  assert.deepEqual(plain(ctx.choices.skipped), []);
});

test('drive save carries excludes and code choices and preserves other volumes', () => {
  let saved;
  const ctx = dialog({ choices: { chosen: ['/m/Photos'], skipped: ['/m/Photos/data'], code: ['/m/repo'] },
    service: { settings: { roots: [{ path: '/h/Docs', volume: 'u', excludes: [] }], codeRoots: ['/h/code'] },
      startIndexing(...args) { saved = args; return true; } } });
  ctx.startIndexing();
  assert.deepEqual(plain(saved), [[{ path: '/h/Docs', volume: 'u', excludes: [] },
    { path: '/m/Photos', volume: 'usb', excludes: ['data'] }], ['/h/code', '/m/repo'], 'usb']);
  assert.equal(ctx.phase, 'run');
});

test('the dialog shows its own error, then the walk, then the drive index run', () => {
  const own = { code: 'drive-not-mounted', title: 'Photos2024 is not connected.',
    detail: 'Connect it, then press Retry.', fix: { kind: 'retry' } };
  const walk = { code: 'scan-failed', title: '/m could not be scanned.',
    detail: 'Permission denied. Press Retry to scan it again.', fix: { kind: 'retry' } };
  const index = { code: 'index-exited', title: 'Indexing stopped.',
    detail: 'The indexer exited with code 2. Open the log for the cause, then press Retry.', fix: { kind: 'retry' } };
  const ctx = dialog({ service: { driveError: own, indexError: index },
    walk: { done: true, error: walk.title, failure: walk } });
  assert.equal(ctx.driveFailure(), own);
  ctx.service.driveError = null;
  assert.equal(ctx.driveFailure(), walk);
  ctx.walk = { done: true, error: '', failure: null };
  assert.equal(ctx.driveFailure(), null);
  ctx.phase = 'run';
  assert.equal(ctx.driveFailure(), index);
});

test('Retry scans the drive again while picking and indexes it again after', () => {
  const calls = [];
  const ctx = dialog({ service: { scanDrive: uuid => calls.push(['scan', uuid]),
    settings: { roots: [], codeRoots: [] },
    startIndexing: (roots, code, volume) => { calls.push(['index', volume]); return true; } } });
  ctx.retry();
  ctx.phase = 'run';
  ctx.retry();
  assert.deepEqual(calls, [['scan', 'usb'], ['index', 'usb']]);
});
