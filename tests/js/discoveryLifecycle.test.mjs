import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { qmlFunctions, qmlSource } from './qmlFunctions.mjs';

const functions = (file, values) => qmlFunctions(file, values).ctx;

test('closing a picker stops its discovery without touching playback in another window', () => {
  let stops = 0;
  const ctx = functions('Overlay.qml', { opened: true, view: 'setup', pendingOpen: null, setup: { item: null }, settingsView: { item: null },
    closeTimer: { stop() {} }, searchView: { stopPlayback() {}, flash: '' }, unmap: { restart() {} },
    service: { stopDiscovery() { stops++; } } });
  ctx.close(); ctx.close();
  assert.equal(stops, 1);
});

test('reopening setup reuses or restarts discovery despite a cached first level', () => {
  let scans = 0;
  const ctx = functions('SetupView.qml', { back: false, step: 2, walkError: '', pickFolders: false, indexPage: {},
    service: { discover: { folders: [] }, folderError: null, scanning: false,
      scan() { scans++; } } });
  ctx.reset();
  assert.equal(scans, 1);
});


test('a reconnected Folders step requests a fresh discovery snapshot', () => {
  let scans = 0;
  const ctx = functions('SetupView.qml', { visible: true, step: 2, walkError: '',
    service: { ready: true, discover: { folders: [] }, folderError: null, scanning: false,
      scan() { scans++; } } });
  const source = qmlSource('SetupView.qml');
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
    service: { discover: { folders: [] }, folderError: null, scanning: false,
      scan() { scans++; } } });
  ctx.showFolders();
  assert.equal(ctx.back, false);
  assert.equal(scans, 1);
});

test('Change folders opens setup at the Folders step until indexing starts', () => {
  let statusAsks = 0;
  const setupItem = { pickFolders: false, resets: 0, reset() { this.resets++; } };
  const ctx = functions('Overlay.qml', { opened: true, view: 'settings', setupFolders: false,
    setup: { item: null }, settingsView: { item: null }, Qt: { callLater() {} },
    service: { requestRuntimeStatus() { statusAsks++; } } });
  ctx.showFolders();
  assert.equal(ctx.view, 'setup');
  assert.equal(ctx.setupFolders, true);
  assert.equal(statusAsks, 1);
  ctx.setup.item = setupItem;
  ctx.view = 'search';
  ctx.showFolders();
  assert.equal(setupItem.pickFolders, true);
  assert.equal(setupItem.resets, 1);

  const view = functions('SetupView.qml', { pickFolders: true, service: { indexPending: false } });
  const source = qmlSource('SetupView.qml');
  const handler = source.match(/function onIndexPendingChanged\(\) \{([^]*?)^    \}/m);
  assert.ok(handler, 'Setup leaves the Folders step when indexing starts');
  vm.runInContext('function pending() {' + handler[1] + '}', view);
  view.pending();
  assert.equal(view.pickFolders, true);
  view.service.indexPending = true;
  view.pending();
  assert.equal(view.pickFolders, false);
});

test('opening the overlay never lands on the Folders step by itself', () => {
  const source = qmlSource('Overlay.qml');
  const open = source.match(/^  function open\(payload\) \{([^]*?)^  \}/m)[1];
  assert.match(open, /setupFolders = false/);
});
