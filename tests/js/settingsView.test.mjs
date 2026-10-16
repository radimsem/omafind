import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { load } from './load.mjs';
import { plain } from './fixtures.mjs';

function functions(path, values) {
  const ctx = vm.createContext({ ...values });
  ctx.root = ctx;
  const source = readFileSync(new URL('../../ui/' + path, import.meta.url), 'utf8');
  for (const match of source.matchAll(/^  function \w+\([^]*?^  \}/gm)) vm.runInContext(match[0], ctx);
  return { ctx, source };
}

function settings(values = {}) {
  const calls = [];
  const { ctx, source } = functions('SettingsView.qml', {
    chosen: '', saving: false, saved: false, saveError: '', menuBusy: false, menuError: '',
    Keycombo: load('keycombo.js'), Errors: load('errors.js'),
    Qt: { Key_Escape: 0x01000000 },
    recorder: { active: false, operation: '', pendingLeave: false, conflict: '', lost: false, exposed: false,
      stop() { calls.push('stop'); } },
    shortcutRow: { take() { calls.push('focus'); } },
    service: { settings: { shortcut: 'SUPER + R', roots: [{ path: '/h/Documents' }] },
      binds: [], bindsReady: true, bindsError: null, menuRow: false,
      getBinds() { calls.push('binds'); },
      saveShortcut(chord, menuRow, done) { calls.push(['save', chord, menuRow]); this.done = done; },
      setMenuRow(on, done) { calls.push(['menu', on]); this.done = done; } },
    backRequested() { calls.push('back'); },
    ...values,
  });
  for (const match of source.matchAll(/^  readonly property \w+ (\w+): ([^\n]*(?:\n    [^\n]+)*)/gm)) {
    if (match[1] === 'panelHeight' || match[1] === 'panelWidth') continue;
    Object.defineProperty(ctx, match[1], { get() { return vm.runInContext(match[2], ctx); } });
  }
  const saveEnabled = () => vm.runInContext(source.match(/id: save\b[^]*?enabled: ([^\n]*)/)[1], ctx);
  return { ctx, source, calls, saveEnabled };
}

test('opening Settings shows the saved shortcut and reads binds and the menu row', () => {
  const { ctx, calls } = settings({ chosen: 'F9', saveError: 'old', menuError: 'old', saved: true });
  ctx.reset();
  assert.equal(ctx.chosen, 'SUPER + R');
  assert.equal(ctx.saveError, '');
  assert.equal(ctx.menuError, '');
  assert.equal(ctx.saved, false);
  assert.deepEqual(calls, ['binds']);
});

test('Save shortcut writes only the chord and leaves the menu row alone', () => {
  const { ctx, calls, saveEnabled } = settings();
  ctx.reset();
  assert.equal(saveEnabled(), false, 'the saved chord needs no save');
  ctx.chosen = 'SUPER + U';
  assert.equal(saveEnabled(), true);
  ctx.saveShortcut();
  assert.deepEqual(calls.at(-1), ['save', 'SUPER + U', false]);
  assert.equal(ctx.saving, true);
  ctx.saveShortcut();
  assert.equal(calls.filter(call => call[0] === 'save').length, 1);
  ctx.service.done(true, '');
  assert.equal(ctx.saving, false);
  assert.equal(ctx.saved, true);
  ctx.chosen = 'SUPER + D';
  ctx.saveShortcut();
  ctx.service.done(false, 'Invalid Hyprland shortcut: SUPER + D');
  assert.equal(ctx.saved, false);
  assert.equal(ctx.saveError, 'Invalid Hyprland shortcut: SUPER + D');
});

test('a taken chord or unread binds block saving', () => {
  const { ctx, saveEnabled } = settings({ chosen: 'SUPER + U' });
  ctx.service.binds = [{ chord: 'Super U', description: 'Updates' }];
  assert.match(ctx.chosenConflict, /Super U is already bound to Updates/);
  assert.equal(saveEnabled(), false);
  ctx.service.binds = [];
  ctx.service.bindsReady = false;
  assert.equal(saveEnabled(), false);
  ctx.service.bindsError = { code: 'binds-failed', title: 'Your Hyprland bindings could not be read.', detail: '' };
  assert.equal(saveEnabled(), true);
});

test('the menu switch adds or removes the row from its current state', () => {
  const { ctx, calls } = settings();
  assert.equal(ctx.menuKnown, true);
  ctx.toggleMenu();
  assert.deepEqual(calls.at(-1), ['menu', true]);
  assert.equal(ctx.menuBusy, true);
  ctx.toggleMenu();
  assert.equal(calls.filter(call => call[0] === 'menu').length, 1);
  ctx.service.done(false, 'Invalid omafind markers');
  assert.equal(ctx.menuBusy, false);
  assert.equal(ctx.menuError, 'Invalid omafind markers');
  ctx.service.menuRow = true;
  ctx.toggleMenu();
  assert.deepEqual(calls.at(-1), ['menu', false]);
  assert.equal(ctx.menuError, '');
});

test('the menu switch waits until the daemon reports the row', () => {
  const { ctx, calls } = settings();
  ctx.service.menuRow = null;
  assert.equal(ctx.menuKnown, false);
  ctx.toggleMenu();
  ctx.service.menuRow = true;
  ctx.service.bindsReady = false;
  assert.equal(ctx.menuKnown, false);
  ctx.toggleMenu();
  assert.equal(calls.length, 0);
});

test('Escape in Settings goes back to search and stops a recording first', () => {
  const { ctx, calls } = settings();
  const event = { key: 0x01000000, accepted: false };
  ctx.handleKey(event);
  assert.equal(event.accepted, true);
  assert.deepEqual(calls, ['stop', 'back']);
  const other = { key: 0x41, accepted: false };
  ctx.handleKey(other);
  assert.equal(other.accepted, false);
});

test('Service reads the menu row from binds and keeps it after a toggle', () => {
  const steps = [];
  const { ctx } = functions('Service.qml', {
    binds: [], bindsReady: false, bindsError: null, menuRow: null,
    Protocol: { decode: JSON.parse }, Errors: load('errors.js'),
  });
  ctx.runSteps = (list, done) => { steps.push(list); ctx.finish = done; };
  ctx.receive(JSON.stringify({ t: 'binds', binds: [], menu: true }));
  assert.equal(ctx.menuRow, true);
  ctx.receive(JSON.stringify({ t: 'binds', binds: [] }));
  assert.equal(ctx.menuRow, null, 'an older daemon leaves the row unknown');
  const results = [];
  ctx.setMenuRow(true, (ok, line) => results.push([ok, line]));
  assert.deepEqual(plain(steps), [[['bindings', 'menu', 'add']]]);
  ctx.finish(true, '');
  assert.equal(ctx.menuRow, true);
  ctx.setMenuRow(false, (ok, line) => results.push([ok, line]));
  assert.deepEqual(plain(steps[1]), [['bindings', 'menu', 'remove']]);
  ctx.finish(false, 'Invalid omafind markers');
  assert.equal(ctx.menuRow, true);
  assert.deepEqual(results, [[true, ''], [false, 'Invalid omafind markers']]);
});

test('Ctrl comma in search asks the overlay for Settings', () => {
  let asked = 0;
  const { ctx } = functions('SearchView.qml', {
    Qt: { Key_Escape: 0x01000000, Key_U: 0x55, Key_Return: 0x01000004, Key_Enter: 0x01000005,
      Key_Space: 0x20, ControlModifier: 0x04000000 },
    KeyMap: load('format.js', 'keys.js'), search: { query: 'router' }, selectedRow: null,
    query: { input: { selectedText: '' } }, progressOpen: false,
    settingsRequested() { asked++; },
  });
  const event = { key: 0x2c, text: ',', modifiers: 0x04000000, accepted: false };
  ctx.handleKey(event);
  assert.equal(asked, 1);
  assert.equal(event.accepted, true);
});

function overlay(values = {}) {
  const calls = [];
  const { ctx } = functions('Overlay.qml', {
    opened: true, view: 'search', setupFolders: false, pendingOpen: null,
    setup: { item: null }, settingsView: { item: null }, Qt: { callLater() {} },
    searchView: { reset() {}, stopPlayback() {}, flash: '' }, closeTimer: { stop() {} }, unmap: { restart() {} },
    service: { warm() {}, send() { return true; }, stopDiscovery() {}, requestRuntimeStatus() {} },
    ...values,
  });
  return { ctx, calls };
}

test('Settings opens over search and Back returns to search', () => {
  const { ctx } = overlay();
  ctx.showSettings();
  assert.equal(ctx.view, 'settings');
  ctx.showSearch();
  assert.equal(ctx.view, 'search');
});

for (const action of ['close', 'showSearch', 'showFolders']) {
  test(`${action} stops the Settings recorder`, () => {
    let stops = 0;
    const { ctx } = overlay({ view: 'settings', settingsView: { item: { stop() { stops++; } } } });
    ctx[action]();
    assert.equal(stops, 1);
  });
}
