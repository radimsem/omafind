import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

function functions(file, values) {
  const ctx = vm.createContext(values);
  ctx.root = ctx;
  const source = readFileSync(new URL(`../../${file}`, import.meta.url), 'utf8');
  for (const match of source.matchAll(/^  function \w+\([^]*?^  \}/gm)) vm.runInContext(match[0], ctx);
  return ctx;
}

test('closing a picker stops its discovery without touching playback in another window', () => {
  let stops = 0;
  const ctx = functions('Overlay.qml', { opened: true, view: 'setup', pendingOpen: null, setup: { item: null },
    closeTimer: { stop() {} }, searchView: { stopPlayback() {}, flash: '' }, unmap: { restart() {} },
    service: { stopDiscovery() { stops++; } } });
  ctx.close(); ctx.close();
  assert.equal(stops, 1);
});

test('reopening setup reuses or restarts discovery despite a cached first level', () => {
  let scans = 0;
  const ctx = functions('SetupView.qml', { back: false, step: 2, walkError: '',
    service: { discover: { folders: [] }, discoverError: '', scanning: false,
      scan() { scans++; } } });
  ctx.reset();
  assert.equal(scans, 1);
});


test('a reconnected Folders step requests a fresh discovery snapshot', () => {
  let scans = 0;
  const ctx = functions('SetupView.qml', { visible: true, step: 2, walkError: '',
    service: { ready: true, discover: { folders: [] }, discoverError: '', scanning: false,
      scan() { scans++; } } });
  const source = readFileSync(new URL('../../SetupView.qml', import.meta.url), 'utf8');
  const handler = source.match(/function onReadyChanged\(\) \{([^]*?)^    \}/m);
  assert.ok(handler, 'Folders step listens for reconnection');
  vm.runInContext('function reconnected() {' + handler[1] + '}', ctx);
  ctx.reconnected();
  assert.equal(scans, 1);
  ctx.visible = false; ctx.reconnected();
  ctx.visible = true; ctx.step = 3; ctx.reconnected();
  ctx.step = 2; ctx.service.ready = false; ctx.reconnected();
  assert.equal(scans, 1);
});

test('Back then Next retries a failed background walk', () => {
  let scans = 0;
  const ctx = functions('SetupView.qml', { back: true, walkError: 'fd failed: Permission denied',
    service: { discover: { folders: [] }, discoverError: '', scanning: false,
      scan() { scans++; } } });
  ctx.showFolders();
  assert.equal(ctx.back, false);
  assert.equal(scans, 1);
});
