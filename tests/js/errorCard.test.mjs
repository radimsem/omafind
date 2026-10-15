import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { load } from './load.mjs';

function card() {
  const ctx = vm.createContext({ error: null, installing: false, waited: 0, Errors: load('errors.js') });
  const source = readFileSync(new URL('../../ui/ErrorCard.qml', import.meta.url), 'utf8');
  for (const match of source.matchAll(/^  function \w+\([^]*?^  \}/gm)) vm.runInContext(match[0], ctx);
  for (const name of ['packages', 'fixKey']) {
    const expression = source.match(new RegExp('readonly property \\w+ ' + name + ': (.*)'))[1];
    Object.defineProperty(ctx, name, { get: () => vm.runInContext(expression, ctx) });
  }
  const changed = source.match(/^  onFixKeyChanged: (.*)$/m)[1];
  ctx.setError = error => {
    const previous = ctx.fixKey;
    ctx.error = error;
    if (ctx.fixKey !== previous) vm.runInContext(changed, ctx);
  };
  return ctx;
}

const missing = packages => ({ code: 'tool-missing', fix: { kind: 'install', packages } });

test('a reused card stops installing when another tool sorts into its index', () => {
  const ctx = card();
  ctx.setError(missing(['tesseract']));
  ctx.installing = true;
  ctx.waited = 2000;
  ctx.setError(missing(['ffmpeg']));
  assert.equal(ctx.installing, false);
  assert.equal(ctx.waited, 0);
});

test('a progress resend keeps installing until any install package changes', () => {
  const ctx = card();
  ctx.setError(missing(['fd', 'ripgrep']));
  ctx.installing = true;
  ctx.waited = 2000;
  ctx.setError(missing(['fd', 'ripgrep']));
  assert.equal(ctx.installing, true);
  assert.equal(ctx.waited, 2000);
  ctx.setError(missing(['fd', 'tesseract']));
  assert.equal(ctx.installing, false);
  assert.equal(ctx.waited, 0);
});
