import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

function pane() {
  const layer = name => ({ name, item: null, preview: null, shown: false, mediaReady: false });
  const first = layer('first'), second = layer('second');
  const gate = { running: false, restart() { this.running = true; }, stop() { this.running = false; } };
  const ctx = vm.createContext({ first, second, front: true, preview: null, gate,
    get current() { return ctx.front ? first : second; } });
  const source = readFileSync(new URL('../../ui/PreviewPane.qml', import.meta.url), 'utf8');
  for (const match of source.matchAll(/^  function \w+\([^]*?^  \}/gm)) vm.runInContext(match[0], ctx);
  return ctx;
}

test('the fade waits for the incoming image and rapid switches show the last selection', () => {
  const ctx = pane();
  ctx.first.item = { id: 'a' }; ctx.first.shown = true;
  ctx.show({ id: 'b' });
  assert.equal(ctx.gate.running, true);
  assert.equal(ctx.first.shown, true);
  ctx.show({ id: 'c' });
  ctx.show({ id: 'd' });
  ctx.second.mediaReady = true;
  ctx.swap();
  assert.equal(ctx.current.item.id, 'd');
  assert.equal(ctx.current.shown, true);
  assert.equal(ctx.first.shown, false);
});

test('clearing a pending selection cancels the gate and ignores a late swap', () => {
  const ctx = pane();
  ctx.first.item = { id: 'a' }; ctx.first.shown = true;
  ctx.show({ id: 'b' });
  ctx.show(null);
  assert.equal(ctx.gate.running, false);
  ctx.swap();
  assert.equal(ctx.first.shown, false);
  assert.equal(ctx.second.shown, false);
});

test('returning to the current selection cancels the pending swap', () => {
  const ctx = pane();
  ctx.first.item = { id: 'a' }; ctx.first.shown = true;
  ctx.show({ id: 'b' });
  ctx.show({ id: 'a' });
  ctx.swap();
  assert.equal(ctx.current.item.id, 'a');
  assert.equal(ctx.current.shown, true);
});

test('a readiness notification and timeout cannot swap twice', () => {
  const ctx = pane();
  ctx.first.item = { id: 'a' }; ctx.first.shown = true;
  ctx.second.mediaReady = true;
  ctx.show({ id: 'b' });
  ctx.swap();
  assert.equal(ctx.current.item.id, 'b');
});

test('a preview error reaches the layer that shows its item', () => {
  const ctx = pane();
  const source = readFileSync(new URL('../../ui/PreviewPane.qml', import.meta.url), 'utf8');
  vm.runInContext('function previewChanged() {' + source.match(/^  onPreviewChanged: \{([^]*?)^  \}/m)[1] + '}', ctx);
  const error = { code: 'file-missing', title: 'a.pdf is missing.', detail: 'It was moved or deleted after it was indexed.' };
  ctx.first.item = { id: 'a' }; ctx.first.shown = true; ctx.pendingSwap = false;
  ctx.preview = { id: 'a', error };
  ctx.previewChanged();
  assert.equal(ctx.first.preview.error, error);
  ctx.show({ id: 'b' });
  ctx.preview = { id: 'b', error };
  ctx.previewChanged();
  assert.equal(ctx.second.preview.error, error);
});
