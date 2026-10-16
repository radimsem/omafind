import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { load } from './load.mjs';
import { plain } from './fixtures.mjs';

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
  const source = readFileSync(new URL('../../ui/SearchView.qml', import.meta.url), 'utf8');
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


test('an early timer tick re-arms the timer for the remaining time', () => {
  const armed = [];
  const timer = { interval: 200, restart() { armed.push(this.interval); } };
  const context = view({
    SearchState: load('format.js', 'results.js', 'searchState.js'),
    service: { send() { return true; } },
    meaningTimer: timer, wordsTimer: { interval: 50, restart() {} },
    Date: { now: () => 1150 },
    search: { query: 'router', seq: 1, phase: 'words', sentWords: 1, sentMeaning: 0,
      reply: null, started: 1000 },
  });
  context.due('meaning-due');
  assert.deepEqual(armed, [50]);
});

test('banner Retry follows the source of the card', () => {
  const calls = [];
  const service = { retryUpdate: () => calls.push('update'), checkUnit: () => calls.push('unit'),
    connectSocket: () => calls.push('connect'), installHelper: () => calls.push('install'), warm: () => calls.push('warm') };
  for (const [retry, expected] of [['update', ['update']], ['connect', ['reload', 'install']], ['warm', ['warm']]]) {
    calls.length = 0;
    view({ service, startLog: { reload: () => calls.push('reload') },
      bannerView: { error: {}, retry } }).retryBanner();
    assert.deepEqual(calls, expected);
  }
});

test('banner Retry on a search error sends the query again', () => {
  const armed = [];
  const context = view({ service: {}, bannerView: { error: {}, retry: 'search' },
    SearchState: load('format.js', 'results.js', 'searchState.js'),
    Date: { now: () => 5000 },
    meaningTimer: { interval: 0, restart() { armed.push(this.interval); } },
    search: { query: 'router', seq: 3, phase: 'done', sentWords: 3, sentMeaning: 3, reply: null, started: 0 } });
  context.retryBanner();
  assert.equal(context.search.seq, 4);
  assert.equal(context.search.phase, 'words');
  assert.deepEqual(armed, [200]);
});

test('a preview error replaces the preview of the selected row', () => {
  const context = view({ Errors: load('errors.js'), selectedItem: { id: 'pdf:1' }, preview: null });
  const reply = { t: 'error', id: 'pdf:1', code: 'file-missing', title: 'a.pdf is missing.',
    detail: 'It was moved or deleted after it was indexed.' };
  context.previewFailed({ ...reply, id: 'pdf:2' });
  context.previewFailed({ ...reply, for: 'open' });
  assert.equal(context.preview, null);
  context.previewFailed(reply);
  assert.deepEqual(plain(context.preview), { id: 'pdf:1', error: { code: 'file-missing',
    title: 'a.pdf is missing.', detail: 'It was moved or deleted after it was indexed.' } });
});


test('the offline banner shows a helper setup failure and keeps its install fix', () => {
  const failure = { code: 'tools-missing', title: 'Some tools omafind needs are missing.',
    detail: 'Missing: fd. Install them, then press Retry.', fix: { kind: 'install', packages: ['fd'] } };
  const ctx = view({ service: { engineError: failure }, daemonDown: true, updateError: null,
    startLog: { loaded: false, path: '/d/start.log' }, reply: null,
    Results: load('format.js', 'errors.js', 'results.js'), Errors: load('errors.js') });
  const source = readFileSync(new URL('../../ui/SearchView.qml', import.meta.url), 'utf8');
  const binding = source.match(/readonly property var bannerView: ([^]*?\}\))/)[1];
  assert.deepEqual(plain(vm.runInContext(binding, ctx)), { error: failure, retry: 'connect' });
  ctx.service.engineError = { code: 'build-failed', title: 'The runtime build failed.', detail: '' };
  assert.equal(vm.runInContext(binding, ctx).error.code, 'daemon-offline');
  ctx.service.engineError = null;
  assert.equal(vm.runInContext(binding, ctx).error.code, 'daemon-offline');
  ctx.startLog.loaded = true;
  assert.equal(vm.runInContext(binding, ctx).error.log, '/d/start.log');
  ctx.daemonDown = false;
  ctx.service.engineError = failure;
  assert.equal(vm.runInContext(binding, ctx), null);
});


test('an update install card offers Retry and auto-retries the update after packages arrive', () => {
  const Update = load('Update.js');
  const failure = { code: 'tools-missing', title: 'Some tools omafind needs are missing.',
    detail: 'Missing: fd. Install them, then press Retry.', fix: { kind: 'install', packages: ['fd'] } };
  const result = Update.reduce({ ...Update.initial(), phase: 'updating' },
    { type: 'setup-exited', ok: false, line: 'sudo pacman -S --needed fd', error: failure });
  const Results = load('format.js', 'errors.js', 'results.js');
  const bannerView = Results.bannerFor({ update: Update.banner(result.state), offline: Results.offline('') });
  assert.equal(bannerView.retry, 'update');
  assert.deepEqual(plain(bannerView.error.fix), failure.fix);
  let retries = 0;
  const context = view({ bannerView, service: { retryUpdate() { retries++; } } });
  context.root = context;
  const source = readFileSync(new URL('../../ui/SearchView.qml', import.meta.url), 'utf8');
  const banner = source.slice(source.indexOf('id: banner'));
  const retryHere = banner.match(/retryHere: ([^\n]+)/)[1];
  const onRetry = banner.match(/onRetry: ([^\n]+)/)[1];
  const commands = [];
  const card = vm.createContext({ error: bannerView.error, Errors: load('errors.js'),
    packages: bannerView.error.fix.packages, installing: false, waited: 0, retryText: 'Retry',
    retryHere: vm.runInContext(retryHere, context),
    retry() { vm.runInContext(onRetry, context); },
    Plugin: { Installer: { install(packages) { commands.push(plain(packages)); } } } });
  card.root = card;
  const cardSource = readFileSync(new URL('../../ui/ErrorCard.qml', import.meta.url), 'utf8');
  for (const match of cardSource.matchAll(/^  function \w+\([^]*?^  \}/gm)) vm.runInContext(match[0], card);
  const retryButton = cardSource.slice(cardSource.indexOf('objectName: root.objectName ? root.objectName + "Retry"'));
  assert.equal(vm.runInContext(retryButton.match(/visible: ([^]*?)\n      focusable:/)[1], card), true);
  vm.runInContext('(function() {' + retryButton.match(/onClicked: \{([^]*?)^      \}/m)[1] + '})()', card);
  assert.equal(retries, 1);
  card.install();
  assert.deepEqual(commands, [['fd']]);
  const present = cardSource.slice(cardSource.indexOf('id: present'));
  const exited = vm.runInContext('(' + present.match(/onExited: ([^]*?)\n  \}/)[1] + ')', card);
  exited(1, 0);
  assert.equal(retries, 1);
  assert.equal(card.installing, true);
  exited(0, 0);
  assert.equal(retries, 2);
  assert.equal(card.installing, false);
  exited(0, 0);
  assert.equal(retries, 2);
});
