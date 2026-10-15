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
