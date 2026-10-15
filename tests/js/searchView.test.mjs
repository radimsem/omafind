import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { load } from './load.mjs';

function view(values = {}) {
  const context = vm.createContext({
    Qt: { Key_Escape: 0x01000000, Key_U: 0x55, Key_Return: 0x01000004,
      Key_Enter: 0x01000005, Key_Space: 0x20, ControlModifier: 0x04000000 },
    KeyMap: load('format.js', 'keys.js'),
    search: { query: 'router' }, selectedRow: null,
    query: { input: { selectedText: '' }, setText() { assert.fail('query cleared'); } },
    closeRequested() { assert.fail('overlay closed'); },
    progressOpen: false,
    ...values,
  });
  const source = readFileSync(new URL('../../SearchView.qml', import.meta.url), 'utf8');
  for (const match of source.matchAll(/^  function \w+\([^]*?^  \}/gm)) {
    vm.runInContext(match[0], context);
  }
  return context;
}

test('Escape closes progress before clearing the query or closing the overlay', () => {
  for (const query of ['', 'router']) {
    const context = view({ progressOpen: true, search: { query } });
    const event = { key: 0x01000000, modifiers: 0, accepted: false };
    context.handleKey(event);
    assert.equal(context.progressOpen, false);
    assert.equal(event.accepted, true);
  }
});

test('Ctrl I requests a progress snapshot only when opening the popover', () => {
  let requests = 0;
  const context = view({ service: { requestProgress() { requests++; } } });
  for (const open of [true, false, true]) {
    const event = { key: 0x49, modifiers: 0x04000000, accepted: false };
    context.handleKey(event);
    assert.equal(context.progressOpen, open);
    assert.equal(event.accepted, true);
  }
  assert.equal(requests, 2);
});

test('Ctrl C with selected query text falls through without copying the path', () => {
  const context = view({
    selectedRow: { type: 'item', item: { kind: 'text', path: '/fixture' } },
    query: { input: { selectedText: 'router' } },
  });
  const event = { key: 0x43, modifiers: 0x04000000, accepted: false };
  context.handleKey(event);
  assert.equal(event.accepted, false);
});


test('Enter toggles weak matches both ways and keeps selection on the fold row', () => {
  const Results = load('format.js', 'results.js');
  const items = [{ id: 'strong', kind: 'image' },
    { id: 'weak', kind: 'image', weak: true }];
  const context = view({ Results, expanded: false, reply: { items },
    rows: Results.group(items, { expanded: false }).rows,
    selectedIndex: 2, userMoved: false });
  for (const expanded of [true, false]) {
    context.selectedRow = context.rows[context.selectedIndex];
    context.handleKey({ key: 0x01000004, modifiers: 0 });
    assert.equal(context.expanded, expanded);
    assert.equal(context.rows[context.selectedIndex].type, 'weak');
    assert.equal(context.rows.length, expanded ? 4 : 3);
    assert.equal(context.userMoved, true);
  }
});
