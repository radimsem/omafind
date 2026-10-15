import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { load } from './load.mjs';

const plain = value => JSON.parse(JSON.stringify(value));

function service(values = {}) {
  const sent = [];
  const ctx = vm.createContext({
    walks: {}, childFolders: {}, childrenAsked: {}, discoverCounts: {}, datasets: {}, repos: {}, worktrees: {},
    scanning: false, driveScanning: false, bindsReady: true, results: null, runtimeProgress: null,
    engineError: null, folderError: null, indexError: null, driveError: null, searchError: null, bindsError: null,
    Protocol: { decode: JSON.parse }, Errors: load('errors.js'),
    setupFailed() {}, warmFailed() {}, resultsReceived() {}, childrenReceived() {},
  });
  const source = readFileSync(new URL('../../Service.qml', import.meta.url), 'utf8');
  for (const match of source.matchAll(/^  function \w+\([^]*?^  \}/gm)) vm.runInContext(match[0], ctx);
  ctx.send = message => { sent.push(message); return true; };
  Object.assign(ctx, values);
  ctx.root = ctx;
  ctx.sent = sent;
  return ctx;
}

const scanFailed = { code: 'scan-failed', title: 'Pictures could not be scanned.',
  detail: 'Permission denied. Press Retry to scan it again.', fix: { kind: 'retry' } };

test('setup errors land on the surface of the request named in for', () => {
  const ctx = service({ scanning: true });
  for (const [kind, surface] of [['runtime_install', 'engineError'], ['runtime_status', 'engineError'],
    ['discover_start', 'folderError'], ['discover_children', 'folderError'], ['fs_list', 'folderError'],
    ['index_start', 'indexError'], ['retry_failed', 'indexError'], ['drive_decision', 'driveError'],
    ['binds_get', 'bindsError']]) {
    ctx.receive(JSON.stringify({ t: 'error', for: kind, ...scanFailed }));
    assert.deepEqual(plain(ctx[surface]), scanFailed, kind);
  }
  assert.equal(ctx.scanning, false);
  assert.equal(ctx.bindsReady, false);
});

test('a failed discover_start goes to the drive dialog while a drive scan runs', () => {
  const ctx = service({ driveScanning: true });
  ctx.receive(JSON.stringify({ t: 'error', for: 'discover_start', code: 'drive-not-mounted',
    title: 'Photos2024 is not connected.', detail: 'Connect it, then press Retry.', fix: { kind: 'retry' } }));
  assert.equal(ctx.driveError.code, 'drive-not-mounted');
  assert.equal(ctx.folderError, null);
  assert.equal(ctx.driveScanning, false);
});

test('the error object keeps its log and an older reason still shows', () => {
  const ctx = service();
  ctx.receive(JSON.stringify({ t: 'error', for: 'index_start', code: 'index-exited', title: 'Indexing stopped.',
    detail: 'The indexer exited with code 2. Open the log for the cause, then press Retry.',
    fix: { kind: 'retry' }, log: '/d/reindex.log' }));
  assert.equal(ctx.indexError.log, '/d/reindex.log');
  ctx.receive(JSON.stringify({ t: 'error', for: 'index_start', code: 'runtime-failed', reason: 'No folders are selected.' }));
  assert.deepEqual(plain(ctx.indexError), { code: 'unknown', title: 'No folders are selected.', detail: '' });
});

test('runtime progress holds the engine error only while it reads failed', () => {
  const ctx = service();
  ctx.receive(JSON.stringify({ t: 'runtime_progress', state: 'failed', build: { state: 'failed' },
    error: { code: 'build-missing-packages', title: 'The search engine could not be built.',
      detail: 'Missing build packages: vulkan-headers. Install them, then press Retry.',
      fix: { kind: 'install', packages: ['vulkan-headers'] } } }));
  assert.equal(ctx.engineError.code, 'build-missing-packages');
  ctx.receive(JSON.stringify({ t: 'runtime_progress', state: 'running', error: null }));
  assert.equal(ctx.engineError, null);
  ctx.receive(JSON.stringify({ t: 'runtime_progress', state: 'failed', reason: 'The runtime build failed: exit 1.' }));
  assert.equal(ctx.engineError.title, 'The runtime build failed: exit 1.');
});

test('warm failures and degraded results arrive as error objects', () => {
  const ctx = service();
  ctx.receive(JSON.stringify({ t: 'warm_failed', error: { code: 'server-start-failed',
    title: 'The embedding server did not start.', detail: 'It exited with code 1. Showing keyword matches until it starts.',
    fix: { kind: 'retry' }, log: '/d/llama-server.log' } }));
  assert.equal(ctx.searchError.code, 'server-start-failed');
  ctx.warm();
  assert.equal(ctx.searchError, null);
  assert.deepEqual(plain(ctx.sent.at(-1)), { t: 'warm' });
  ctx.receive(JSON.stringify({ t: 'warm_failed', reason: 'Vulkan device lost' }));
  assert.equal(ctx.searchError.title, 'Vulkan device lost');
  ctx.receive(JSON.stringify({ t: 'results', seq: 1, items: [], degraded: 'indexing in progress' }));
  assert.deepEqual(plain(ctx.results.degraded), { code: 'unknown', title: 'indexing in progress', detail: '' });
  ctx.receive(JSON.stringify({ t: 'results', seq: 2, items: [], degraded: null }));
  assert.equal(ctx.results.degraded, null);
});

test('a failed helper install reads the json line, then stderr', () => {
  const ctx = service();
  const missing = { code: 'tools-missing', title: 'Some tools omafind needs are missing.',
    detail: 'Missing: fd. Install them, then press Retry.', fix: { kind: 'install', packages: ['fd'] } };
  assert.deepEqual(plain(ctx.helperFailure('syncing\n' + JSON.stringify({ ok: false, error: missing }) + '\n', 'warning\n')), missing);
  assert.deepEqual(plain(ctx.helperFailure('', 'uv: command not found\n\n')),
    { code: 'unknown', title: 'uv: command not found', detail: '' });
  assert.equal(ctx.helperFailure('{"ok": true}', '').title, 'The omafind helper could not be installed.');
});

test('walk and child errors keep one fact and give the folder step the object', () => {
  const ctx = service();
  ctx.receiveCounts({ root: '/h', counts: {}, done: true, error: scanFailed });
  assert.equal(ctx.walks['/h'].error, 'Pictures could not be scanned.');
  assert.equal(ctx.folderError.code, 'scan-failed');
  ctx.receive(JSON.stringify({ t: 'discover_children', path: '/h/a', dirs: [], error: scanFailed }));
  assert.equal(ctx.childFolders['/h/a'].error, 'Pictures could not be scanned.');
  ctx.receive(JSON.stringify({ t: 'discover_children', path: '/h/b', dirs: [], error: 'Permission denied' }));
  assert.equal(ctx.childFolders['/h/b'].error, 'Permission denied');
});

test('a folder save that fails reports on the surface that asked', () => {
  const ctx = service({ persist() { return false; }, indexTimer: { restart() {} } });
  assert.equal(ctx.startIndexing([], [], ''), false);
  assert.match(ctx.folderError.title, /press Start indexing again\.$/);
  assert.equal(ctx.indexError, null);
  assert.equal(ctx.startIndexing([], [], 'usb'), false);
  assert.match(ctx.driveError.title, /press Index this drive again\.$/);
});

test('binds offline and retry_failed requests', () => {
  const ctx = service();
  ctx.retryFailed('tool-missing');
  assert.deepEqual(plain(ctx.sent.at(-1)), { t: 'retry_failed', code: 'tool-missing' });
  ctx.send = () => false;
  ctx.getBinds();
  assert.equal(ctx.bindsError.code, 'daemon-offline');
});

test('starting an action clears the error on its own surface', () => {
  const ctx = service({ engineError: scanFailed, folderError: scanFailed, indexError: scanFailed,
    driveError: scanFailed, helperRunning: false, helperSetup: { running: false },
    persist: () => true, indexTimer: { restart() {} } });
  ctx.runtimeInstall();
  assert.equal(ctx.engineError, null);
  ctx.engineError = scanFailed;
  ctx.installHelper();
  assert.equal(ctx.engineError, null);
  ctx.scan();
  assert.equal(ctx.folderError, null);
  ctx.startIndexing(['~'], [], '');
  assert.equal(ctx.indexError, null);
  ctx.scanDrive('usb');
  assert.equal(ctx.driveError, null);
});


test('a ready connection retries only an offline binds request', () => {
  const ctx = service({ Connection: load('Connection.js'),
    connection: { unit: 'enabled', socket: 'connecting', failures: 1 },
    runtimeAsked: true, reduceUpdate() {} });
  Object.defineProperty(ctx, 'ready', { get() { return ctx.connection.socket === 'ready'; } });
  ctx.send = () => false;
  ctx.getBinds();
  ctx.send = message => { assert.equal(ctx.ready, true); ctx.sent.push(message); return true; };
  const state = { runtime: 'ready', model: 'ready', embedder: 'stopped', build: 'b' };
  ctx.receiveState(state);
  assert.deepEqual(plain(ctx.sent), [{ t: 'binds_get' }]);
  assert.equal(ctx.bindsError, null);
  assert.equal(ctx.bindsReady, false);
  ctx.receiveState(state);
  ctx.bindsError = scanFailed;
  ctx.receiveState(state);
  assert.equal(ctx.sent.length, 1);
  assert.equal(ctx.bindsError, scanFailed);
});
