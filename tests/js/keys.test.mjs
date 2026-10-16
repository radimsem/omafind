import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
import { fixture, freeze, plain } from './fixtures.mjs';

test('Escape clears a query before closing the overlay', () => {
  const { action } = load('format.js', 'keys.js');
  const event = freeze({ key: 0x01000000, text: '', modifiers: 0 });
  assert.equal(action(event, { query: 'router', row: null }), 'clear');
  assert.equal(action(event, { query: '', row: null }), 'close');
});

test('arrows and Ctrl or Alt J/K navigate while ordinary typing remains inert', () => {
  const { action } = load('format.js', 'keys.js');
  for (const [key, modifiers, want] of [[0x01000013, 0, 'up'], [0x01000015, 0, 'down'],
    [0x4a, 0x04000000, 'down'], [0x4b, 0x04000000, 'up'],
    [0x4a, 0x08000000, 'down'], [0x4b, 0x08000000, 'up'],
    [0x4a, 0, null], [0x4b, 0x02000000, null], [0x43, 0, null], [0x41, 0, null]]) {
    assert.equal(action({ key, text: '', modifiers }, { query: '', row: null }), want);
  }
});

test('Enter opens items, Ctrl Enter reveals, and weak or offline rows restrict actions', () => {
  const { action } = load('format.js', 'keys.js');
  const row = freeze({ type: 'item', item: fixture('pdf').items[0] });
  for (const key of [0x01000004, 0x01000005]) {
    assert.equal(action({ key, modifiers: 0 }, { row }), 'open');
    assert.equal(action({ key, modifiers: 0x04000000 }, { row }), 'reveal');
    assert.equal(action({ key, modifiers: 0 }, { row: { type: 'weak' } }), 'toggle-weak');
    assert.equal(action({ key, modifiers: 0 }, { row: null }), null);
    assert.equal(action({ key, modifiers: 0 }, { row: { type: 'header' } }), null);
  }
  const offline = freeze({ type: 'item', item: fixture('offline').items[0] });
  for (const [key, modifiers, want] of [[0x01000004, 0, null], [0x01000004, 0x04000000, null],
    [0x20, 0x04000000, null], [0x43, 0x04000000, 'copy']]) {
    assert.equal(action({ key, modifiers }, { row: offline }), want);
  }
  assert.equal(action({ key: 0x43, modifiers: 0x04000000 }, { row }), 'copy');
  assert.equal(action({ key: 0x43, modifiers: 0x04000000 }, { row: { type: 'weak' } }), null);
});

test('Ctrl Space plays only online audio and video selections', () => {
  const { action } = load('format.js', 'keys.js');
  for (const kind of ['image', 'video', 'audio', 'pdf', 'text', 'code']) {
    const item = fixture(kind).items[0];
    assert.equal(action({ key: 0x20, modifiers: 0x04000000 }, { row: { type: 'item', item } }),
      ['audio', 'video'].includes(kind) ? 'play' : null);
  }
});

test('hints follow jump targets and offer Ctrl Space only for audio and video', () => {
  const { hints } = load('format.js', 'keys.js');
  for (const [kind, open, play] of [['image', 'open', null],
    ['video', 'open at 14:32', 'play at 14:32'],
    ['audio', 'open at 7:55', 'play at 7:55'],
    ['pdf', 'open at page 12', null], ['text', 'open at line 41', null],
    ['code', 'open at line 8', null]]) {
    const want = [{ keys: ['Enter'], label: open },
      { keys: ['Ctrl', 'Enter'], label: 'show in folder' }];
    if (play) want.push({ keys: ['Ctrl', 'Space'], label: play });
    want.push({ keys: ['Ctrl', 'C'], label: 'copy path' }, { keys: ['Esc'], label: 'close' });
    assert.deepEqual(plain(hints(freeze({ type: 'item', item: fixture(kind).items[0] }))), want);
  }
  assert.deepEqual(plain(hints({ type: 'item', item: fixture('offline').items[0] })), [
    { keys: ['Ctrl', 'C'], label: 'copy path' }, { keys: ['Esc'], label: 'close' }
  ]);
  assert.deepEqual(plain(hints({ type: 'weak', expanded: false })), [
    { keys: ['Enter'], label: 'expand' }, { keys: ['Esc'], label: 'close' }
  ]);
  assert.deepEqual(plain(hints({ type: 'weak', expanded: true })), [
    { keys: ['Enter'], label: 'collapse' }, { keys: ['Esc'], label: 'close' }
  ]);
  assert.deepEqual(plain(hints(null)), [{ keys: ['Esc'], label: 'close' }]);
});

test('editor names use basenames and actions name the actual opening line', () => {
  const { editorName, actionLabel } = load('format.js', 'keys.js');
  for (const [raw, name] of [['nvim', 'Neovim'], ['/usr/bin/vim', 'Vim'], ['hx', 'Helix'],
    ['emacs', 'Emacs'], ['zed', 'Zed'], ['code', 'VS Code'], ['/usr/bin/nano', 'Nano']]) {
    assert.equal(editorName(raw), name);
  }
  for (const [item, name, want] of [[fixture('image').items[0], 'Neovim', 'Open'],
    [fixture('video').items[0], 'Neovim', 'Open at 14:32'],
    [fixture('audio').items[0], 'Neovim', 'Open at 7:55'],
    [fixture('pdf').items[0], 'Neovim', 'Open at page 12'],
    [{ kind: 'text', loc: 212, loc_end: 222 }, 'Neovim', 'Open in Neovim at line 212'],
    [fixture('code').items[0], 'Neovim', 'Open in Neovim at line 8']]) {
    assert.equal(actionLabel(freeze(item), name), want);
  }
});


test('preview jumps override source lines without mutating items', () => {
  const { hints, actionLabel } = load('format.js', 'keys.js');
  for (const item of [{ kind: 'text', loc: 41 }, { kind: 'code', loc: 41, open_line: 8 },
    { kind: 'text', loc: null }]) {
    freeze(item);
    assert.equal(hints({ type: 'item', item }, 212)[0].label, 'open at line 212');
    assert.equal(actionLabel(item, 'Neovim', 212), 'Open in Neovim at line 212');
    assert.equal(item.loc, item.kind === 'text' && item.loc == null ? null : 41);
  }
});

test('Ctrl N and P move, page keys page, and Ctrl Home and End jump to the ends', () => {
  const { action } = load('format.js', 'keys.js');
  const CTRL = 0x04000000;
  for (const [key, modifiers, want] of [[0x4e, CTRL, 'down'], [0x50, CTRL, 'up'],
    [0x4e, 0, null], [0x50, 0, null],
    [0x01000017, 0, 'pagedown'], [0x01000016, 0, 'pageup'],
    [0x01000010, CTRL, 'first'], [0x01000011, CTRL, 'last'],
    [0x01000010, 0, null], [0x01000011, 0, null]]) {
    assert.equal(action({ key, text: '', modifiers }, { query: 'q', row: null }), want);
  }
});

test('Ctrl C with a query selection is left to the text field', () => {
  const { action } = load('format.js', 'keys.js');
  const row = freeze({ type: 'item', item: fixture('pdf').items[0] });
  const ctrlC = { key: 0x43, modifiers: 0x04000000 };
  assert.equal(action(ctrlC, { row, selection: true }), null);
  assert.equal(action(ctrlC, { row, selection: false }), 'copy');
});

test('Ctrl I toggles the progress popover with or without a selection', () => {
  const { action } = load('format.js', 'keys.js');
  const ctrlI = { key: 0x49, modifiers: 0x04000000 };
  assert.equal(action(ctrlI, { query: '', row: null }), 'progress');
  assert.equal(action(ctrlI, { query: 'x', row: { type: 'item', item: fixture('pdf').items[0] } }), 'progress');
  assert.equal(action({ key: 0x49, modifiers: 0 }, { query: '', row: null }), null);
});

test('Ctrl comma opens settings from any selection, a bare comma stays text', () => {
  const { action } = load('format.js', 'keys.js');
  const item = { type: 'item', item: { kind: 'text', loc: 3 } };
  for (const ctx of [{ query: '', row: null }, { query: 'router', row: item }, { query: '', row: { type: 'weak' } }]) {
    assert.equal(action({ key: 0x2c, text: ',', modifiers: 0x04000000 }, ctx), 'settings');
    assert.equal(action({ key: 0x2c, text: ',', modifiers: 0 }, ctx), null);
  }
});

test('the idle footer offers settings beside progress and close', () => {
  const { idleHints } = load('format.js', 'keys.js');
  const settings = { keys: ['Ctrl', ','], label: 'settings' };
  const close = { keys: ['Esc'], label: 'close' };
  assert.deepEqual(plain(idleHints(false)), [settings, close]);
  assert.deepEqual(plain(idleHints(true)), [{ keys: ['Ctrl', 'I'], label: 'progress' }, settings, close]);
});
