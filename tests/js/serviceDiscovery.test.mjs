import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { load } from './load.mjs';

function service(values = {}) {
  const ctx = vm.createContext({
    discoverCounts: {}, walks: {}, datasets: {}, repos: {}, worktrees: {}, childFolders: {}, childrenAsked: {},
    Protocol: { decode: JSON.parse }, Errors: load('errors.js'), childrenReceived() {}, setupFailed() {},
    send() { return true; }, ...values,
  });
  const source = readFileSync(new URL('../../Service.qml', import.meta.url), 'utf8');
  for (const match of source.matchAll(/^  function \w+\([^]*?^  \}/gm))
    vm.runInContext(match[0], ctx);
  for (const match of source.matchAll(/^  function \w+\([^\n]*\) \{[^\n]*\}$/gm))
    vm.runInContext(match[0], ctx);
  Object.assign(ctx, values);
  return ctx;
}
const plain = value => JSON.parse(JSON.stringify(value));

test('counts merge batches and retain errors and dataset evidence', () => {
  const ctx = service();
  ctx.receiveCounts({ root: '/h', counts: { '/h/a': { text: 2 } }, done: false });
  ctx.receiveCounts({ root: '/h', counts: { '/h/b': { pdf: 1 } }, done: true,
    seconds: 0.4, error: 'fd failed', datasets: [{ path: '/h/a/data', kind: 'image' }] });
  assert.deepEqual(plain(ctx.discoverCounts), { '/h/a': { text: 2 }, '/h/b': { pdf: 1 } });
  assert.deepEqual(plain(ctx.walks['/h']), { done: true, seconds: 0.4, error: 'fd failed',
    failure: { code: 'unknown', title: 'fd failed', detail: '' } });
  assert.equal(ctx.datasets['/h/a/data'].kind, 'image');
});

test('children requests send once and failed sends can be retried', () => {
  let calls = 0;
  let connected = false;
  const ctx = service({ send() { calls++; return connected; } });
  assert.equal(ctx.requestChildren('/h/a'), false);
  connected = true;
  assert.equal(ctx.requestChildren('/h/a'), true);
  assert.equal(ctx.requestChildren('/h/a'), true);
  assert.equal(calls, 2);
  ctx.receive(JSON.stringify({ t: 'discover_children', path: '/h/a', dirs: [], volume: 'u' }));
  assert.deepEqual(plain(ctx.childFolders['/h/a']), { dirs: [], volume: 'u', error: '' });
  ctx.requestChildren('/h/a');
  assert.equal(calls, 2);
});

test('drive indexing persists code toggles without marking setup done', () => {
  let saved;
  let timers = 0;
  const ctx = service({ persist(changes) { saved = plain(changes); return true; },
    indexTimer: { restart() { timers++; } } });
  assert.equal(ctx.startIndexing([{ path: '/m/docs', volume: 'usb', excludes: [] }], ['/m/repo'], 'usb'), true);
  assert.deepEqual(saved, { roots: [{ path: '/m/docs', volume: 'usb', excludes: [] }], codeRoots: ['/m/repo'] });
  assert.equal(ctx.indexVolume, 'usb');
  assert.equal(timers, 1);
});

test('an unreadable children reply can be retried', () => {
  let sends = 0;
  const ctx = service({ send() { sends++; return true; } });
  ctx.requestChildren('/h/a');
  ctx.receive(JSON.stringify({ t: 'discover_children', path: '/h/a', dirs: [], error: 'Permission denied' }));
  ctx.requestChildren('/h/a');
  assert.equal(sends, 2);
});

test('a fresh walk clears stale counts and dataset proposals only under its root', () => {
  const ctx = service({ discoverCounts: { '/h/a': { text: 9 }, '/m/b': { text: 1 } },
    datasets: { '/h/a': { path: '/h/a' }, '/m/b': { path: '/m/b' } } });
  ctx.receiveCounts({ root: '/h', counts: {}, done: false, reset: true });
  assert.deepEqual(plain(ctx.discoverCounts), { '/m/b': { text: 1 } });
  assert.deepEqual(Object.keys(ctx.datasets), ['/m/b']);
});


test('stopping a pending picker clears scanning so reopening can request discovery', () => {
  const ctx = service({ scanning: true, driveScanning: true,
    walks: { '/h': { done: false, seconds: null, error: '' } }, send() { return true; } });
  ctx.stopDiscovery();
  assert.equal(ctx.scanning, false);
  assert.equal(ctx.driveScanning, false);
  assert.equal(ctx.walks['/h'].done, true);
  assert.equal(ctx.scan(), true);
});

test('a delayed children snapshot preserves newer streamed counts', () => {
  const ctx = service();
  ctx.receiveCounts({ root: '/h', counts: { '/h/a': { text: 9 } }, done: true });
  ctx.receive(JSON.stringify({ t: 'discover_children', path: '/h',
    dirs: [{ path: '/h/a', counts: { text: 3 } }], volume: 'u' }));
  assert.equal(ctx.discoverCounts['/h/a'].text, 9);
});


test('socket loss finishes open walks and preserves completed walks', () => {
  const ctx = service({ attemptOpen: true, runtimeAsked: true, scanning: true, driveScanning: true,
    walks: { '/h': { done: false, seconds: null, error: '' }, '/m': { done: true, seconds: 1, error: '' } },
    Connection: load('Connection.js'), connection: { unit: 'enabled', socket: 'ready', failures: 0 },
    closeSocket() {}, reconnect: { restart() {} } });
  ctx.attemptFailed();
  assert.deepEqual(plain(ctx.walks['/h']), { done: true, seconds: null, error: 'Connection lost' });
  assert.deepEqual(plain(ctx.walks['/m']), { done: true, seconds: 1, error: '' });
  assert.equal(ctx.scanning, false);
  assert.equal(ctx.driveScanning, false);
});

test('dataset evidence from a child reply joins streamed proposals', () => {
  const ctx = service();
  ctx.receive(JSON.stringify({ t: 'discover_children', path: '/h/Photos', dirs: [
    { path: '/h/Photos/data', rule: 'dataset', evidence: { kind: 'image', files: 300, named: 100 } }
  ] }));
  assert.deepEqual(plain(ctx.datasets['/h/Photos/data']),
    { path: '/h/Photos/data', kind: 'image', files: 300, named: 100 });
});

test('stopping discovery forgets children requests the daemon will not answer', () => {
  let sends = 0;
  const ctx = service({ send() { sends++; return true; } });
  ctx.requestChildren('/h/a');
  ctx.stopDiscovery();
  ctx.requestChildren('/h/a');
  assert.equal(sends, 3);
});

test('a fresh walk keeps the volume of a folder added outside every root', () => {
  const ctx = service();
  ctx.receive(JSON.stringify({ t: 'discover_children', path: '/srv/data', dirs: [], volume: 'u' }));
  ctx.receiveCounts({ root: '/srv/data', counts: {}, done: false, reset: true });
  assert.equal(ctx.childFolders['/srv/data'].volume, 'u');
});

test('the final walk batch records repos and worktrees and a reset clears them', () => {
  const ctx = service();
  ctx.receiveCounts({ root: '/h', counts: {}, done: true, datasets: [],
    repos: ['/h/p/main'], worktrees: ['/h/p/wt'] });
  assert.deepEqual(Object.keys(ctx.repos), ['/h/p/main']);
  assert.deepEqual(Object.keys(ctx.worktrees), ['/h/p/wt']);
  ctx.receiveCounts({ root: '/h', counts: {}, reset: true });
  assert.deepEqual(Object.keys(ctx.repos), []);
});

test('worktree exclusions are known before repo proposals notify the folders step', () => {
  const ctx = service();
  let repos = ctx.repos;
  const snapshots = [];
  Object.defineProperty(ctx, 'repos', { get: () => repos, set(value) {
    repos = value;
    snapshots.push(Object.keys(ctx.worktrees));
  } });
  ctx.receiveCounts({ root: '/h', counts: {}, done: true,
    repos: ['/h/wt/nested'], worktrees: ['/h/wt'] });
  assert.deepEqual(snapshots.at(-1), ['/h/wt']);
});

test('finished walks notify after dataset and worktree exclusions are known', () => {
  const ctx = service();
  let walks = ctx.walks;
  const snapshots = [];
  Object.defineProperty(ctx, 'walks', { get: () => walks, set(value) {
    walks = value;
    if (value['/h'].done) snapshots.push([Object.keys(ctx.datasets), Object.keys(ctx.worktrees)]);
  } });
  ctx.receiveCounts({ root: '/h', counts: {}, done: true,
    datasets: [{ path: '/h/data' }], worktrees: ['/h/wt'], repos: ['/h/main'] });
  assert.deepEqual(snapshots, [[['/h/data'], ['/h/wt']]]);
});

test('a rescan forgets the finished walk so its next finish sorts the folders again', () => {
  const ctx = service();
  ctx.receiveCounts({ root: '/h', counts: { '/h/a': { text: 2 } }, done: true });
  ctx.receiveCounts({ root: '/m', counts: { '/m/b': { pdf: 1 } }, done: true });
  ctx.receive(JSON.stringify({ t: 'discover_result', roots: [{ path: '/h' }], folders: [] }));
  assert.equal(ctx.walks['/h'], undefined);
  assert.equal(ctx.walks['/m'].done, true);
});

test('a home walk reset keeps the replayed walk of a drive mounted inside home', () => {
  const ctx = service();
  ctx.receiveCounts({ root: '/h/disk', counts: { '/h/disk/p': { image: 3 } }, done: true });
  ctx.receiveCounts({ root: '/h', counts: { '/h/a': { text: 2 } }, done: false, reset: true });
  assert.equal(ctx.walks['/h/disk'].done, true);
  assert.deepEqual(plain(ctx.discoverCounts['/h/disk/p']), { image: 3 });
  ctx.receiveCounts({ root: '/h', counts: {}, done: false, reset: true });
  assert.equal(ctx.discoverCounts['/h/a'], undefined);
});
