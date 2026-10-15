import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { load } from './load.mjs';
const plain = value => JSON.parse(JSON.stringify(value));

function folders(values = {}) {
  const ctx = vm.createContext({ Tree: load('tree.js'), seeded: true, proposed: [],
    choices: { chosen: [], skipped: [], code: [] },
    service: { datasets: { '/h/Photos/data': { path: '/h/Photos/data' } } }, ...values });
  ctx.root = ctx;
  const source = readFileSync(new URL('../../ui/SetupFolders.qml', import.meta.url), 'utf8');
  for (const match of source.matchAll(/^  function \w+\([^]*?^  \}/gm)) vm.runInContext(match[0], ctx);
  const handler = source.match(/^  onChoicesChanged: (.*)$/m);
  vm.runInContext('function choicesChanged() {' + (handler ? handler[1] : '') + '}', ctx);
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
