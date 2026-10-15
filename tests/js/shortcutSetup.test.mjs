import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { load } from './load.mjs';

function functions(path, values) {
  const ctx = vm.createContext({ ...values });
  const source = readFileSync(new URL('../../' + path, import.meta.url), 'utf8');
  for (const match of source.matchAll(/^  function \w+\([^]*?^  \}/gm)) vm.runInContext(match[0], ctx);
  Object.assign(ctx, values);
  ctx.root = ctx;
  return { ctx, source };
}

test('Service requests live binds and routes replies and errors', () => {
  const sent = [];
  const { ctx } = functions('Service.qml', {
    binds: [], bindsReady: true, bindsError: { code: 'unknown', title: 'old', detail: '' }, driveScanning: false,
    Protocol: { decode: JSON.parse }, Errors: load('errors.js'),
    send(message) { sent.push(message); return true; }, setupFailed() {},
  });
  ctx.getBinds();
  assert.equal(sent[0].t, 'binds_get');
  assert.equal(ctx.bindsReady, false);
  assert.equal(ctx.bindsError, null);
  ctx.receive(JSON.stringify({ t: 'binds', binds: [{ chord: 'F9', description: 'Menu' }] }));
  assert.equal(ctx.bindsReady, true);
  assert.equal(ctx.binds[0].chord, 'F9');
  ctx.getBinds();
  ctx.receive(JSON.stringify({ t: 'error', for: 'binds_get', code: 'binds-failed',
    title: 'Your Hyprland bindings could not be read.', detail: 'Hyprland is not running. The shortcut was not saved.',
    fix: { kind: 'retry' } }));
  assert.equal(ctx.bindsReady, false);
  assert.equal(ctx.bindsError.code, 'binds-failed');
  ctx.receive(JSON.stringify({ t: 'error', for: 'binds_get', reason: 'Cannot read binds.' }));
  assert.equal(ctx.bindsError.title, 'Cannot read binds.');
  ctx.send = () => false;
  ctx.getBinds();
  assert.match(ctx.bindsError.title, /not running/);
});

test('Index step checks any saved chord and preserves the save workflow', () => {
  const calls = [];
  const { ctx, source } = functions('ui/SetupIndex.qml', {
    chosen: '', saving: false, saveError: '', menuRow: true,
    service: { settings: { shortcut: 'SUPER + SHIFT + H' }, getBinds() { calls.push('binds'); },
      saveShortcut(chord, menuRow, done) { calls.push([chord, menuRow]); done(true, ''); } },
    searchRequested() { calls.push('search'); },
  });
  ctx.root = ctx;
  ctx.begin();
  assert.equal(ctx.chosen, 'SUPER + SHIFT + H');
  assert.deepEqual(calls, ['binds']);
  ctx.saveShortcut();
  assert.deepEqual(calls, ['binds', ['SUPER + SHIFT + H', true], 'search']);
  assert.equal(ctx.saving, false);
  assert.doesNotMatch(source, /nextChord|chordKeys|shortcutLine|bindingChecks/);
  assert.match(source, /enabled: root.chosen[^\n]+!recorder.active/);
});

test('the shortcut row captures Space and Return, cancels on focus loss and leaves Tab alone', () => {
  const { ctx, source } = functions('ui/ShortcutRow.qml', {
    recording: true, canChange: true, Qt: { Key_Tab: 1, Key_Backtab: 2, Key_Space: 32, Key_Return: 4, Key_Enter: 5 },
    captured(key) { this.keys.push(key); }, keys: [], cancel() { this.cancelled = true; },
    button: { forceActiveFocus() {} },
  });
  ctx.root = ctx;
  vm.runInContext('pressKey = ' + source.match(/Keys.onPressed: (event => \{[^]*?)\n    onActiveFocusChanged/)[1].trim(), ctx);
  for (const key of [32, 4]) {
    const event = { key, modifiers: 0, isAutoRepeat: false };
    ctx.pressKey(event);
    assert.equal(event.accepted, true);
  }
  assert.deepEqual(Array.from(ctx.keys), [32, 4]);
  const tab = { key: 1, accepted: false };
  ctx.pressKey(tab);
  assert.equal(tab.accepted, false);
  ctx.pressKey({ key: 32, isAutoRepeat: true });
  assert.equal(ctx.keys.length, 2);
  ctx.activeFocus = false;
  vm.runInContext(source.match(/onActiveFocusChanged: ([^\n]*)/)[1], ctx);
  assert.equal(ctx.cancelled, true);
});

function index(values = {}) {
  const { ctx, source } = functions('ui/SetupIndex.qml', {
    chosen: 'F9', saving: false, Keycombo: load('keycombo.js'),
    service: { binds: [], bindsReady: true, bindsError: null },
    recorder: { active: false, operation: '', pendingLeave: false, conflict: '', lost: false, exposed: false },
    ...values,
  });
  ctx.root = ctx;
  for (const match of source.matchAll(/^  readonly property \w+ (\w+): ([^\n]*(?:\n    [^\n]+)*)/gm)) {
    Object.defineProperty(ctx, match[1], { get() { return vm.runInContext(match[2], ctx); } });
  }
  const row = source.match(/    ShortcutRow \{([^]*?)^    \}/m)[1];
  const rowValue = name => vm.runInContext(row.match(new RegExp(`      ${name}: ([^\n]*(?:\n        [^\n]+)*)`))[1], ctx);
  const saveEnabled = () => vm.runInContext(source.match(/enabled: (root.chosen[^\n]*)/)[1], ctx);
  return { ctx, rowValue, saveEnabled };
}

test('saving allows unknown binds after an error but waits for cleanup', () => {
  const { ctx, rowValue, saveEnabled } = index();
  ctx.service.bindsReady = false;
  assert.equal(saveEnabled(), false);
  ctx.service.bindsError = { code: 'binds-failed', title: 'Your Hyprland bindings could not be read.', detail: '' };
  assert.equal(saveEnabled(), true);
  // The binds card shows the failure, so the shortcut note stays empty.
  assert.equal(rowValue('note'), '');
  ctx.recorder.operation = 'leave';
  assert.equal(saveEnabled(), false);
  ctx.recorder.operation = '';
  ctx.recorder.pendingLeave = true;
  assert.equal(saveEnabled(), false);
});

test('chosenConflict checks saved chords and unsupported chords show their raw text', () => {
  const { ctx, rowValue, saveEnabled } = index();
  ctx.chosen = 'SUPER + SHIFT + H';
  ctx.service.binds = [{ chord: 'Super Shift H', description: 'Hardware' }];
  assert.equal(ctx.chosenConflict, 'Super Shift H is already bound to Hardware in Hyprland. Press another shortcut.');
  assert.equal(saveEnabled(), false);
  ctx.service.binds = [];
  assert.equal(ctx.chosenConflict, '');
  assert.equal(saveEnabled(), true);
  for (const chord of ['SUPER + MINUS', 'SUPER + PRINT']) {
    ctx.chosen = chord;
    assert.equal(ctx.chosenConflict, '');
    assert.deepEqual(Array.from(rowValue('parts')), [chord]);
    assert.equal(saveEnabled(), true);
  }
});

test('a saved chord without Super can still be saved', () => {
  const { ctx, saveEnabled } = index();
  ctx.chosen = 'CTRL + ALT + T';
  ctx.service.binds = [];
  assert.equal(ctx.chosenConflict, '');
  assert.equal(saveEnabled(), true);
  ctx.service.binds = [{ chord: 'Ctrl Alt T', description: 'Terminal' }];
  assert.equal(ctx.chosenConflict, 'Ctrl Alt T is already bound to Terminal in Hyprland. Press another shortcut.');
});

test('Change stays enabled during leave so the row keeps keyboard focus', () => {
  const { ctx, rowValue } = index();
  assert.equal(rowValue('canChange'), true);
  ctx.recorder.operation = 'leave';
  assert.equal(rowValue('canChange'), true);
  ctx.service.bindsReady = false;
  assert.equal(rowValue('canChange'), false);
});

test('reopening the Index step retries the binds read without replacing the chosen chord', () => {
  let requests = 0;
  const { ctx } = functions('SetupView.qml', { back: false, step: 3,
    service: { getBinds() { requests++; } } });
  ctx.reset();
  assert.equal(requests, 1);
});

for (const action of ['close', 'dismiss', 'toggle', 'showSearch']) {
  test(`${action} stops the setup recorder through the loaded view`, () => {
    let stops = 0;
    const page = functions('ui/SetupIndex.qml', { recorder: { stop() { stops++; } } }).ctx;
    const setup = functions('SetupView.qml', { indexPage: page }).ctx;
    const { ctx } = functions('Overlay.qml', {
      opened: true, view: 'setup', pendingOpen: null, setup: { item: setup },
      service: null, shell: null, manifest: null,
      closeTimer: { stop() {} }, unmap: { restart() {} },
      searchView: { stopPlayback() {}, reset() {}, flash: '' }, Qt: { callLater() {} },
    });
    ctx[action]();
    assert.equal(stops, 1);
    if (action !== 'showSearch') assert.equal(ctx.opened, false);
  });
}
