import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
import { freeze, plain } from './fixtures.mjs';

const D = load('errors.js', 'discovery.js');

// Applies the events in order and collects every effect.
function run(start, ...events) {
  let state = freeze(Object.assign(D.initial(), start));
  let effects = [];
  for (const event of events) {
    const result = D.reduce(state, freeze(event));
    state = freeze(result.state);
    effects = effects.concat(result.effects);
  }
  return { state, effects: plain(effects) };
}
const message = body => ({ type: body.t, message: body });
const counts = body => message({ t: 'discover_counts', ...body });
const children = body => message({ t: 'discover_children', ...body });
const sends = effects => effects.filter(e => e.type === 'send').map(e => e.message);
const errors = effects => effects.filter(e => e.type === 'error');

const scanFailed = { code: 'scan-failed', title: 'Pictures could not be scanned.',
  detail: 'Permission denied. Press Retry to scan it again.', fix: { kind: 'retry' } };

test('the initial state has no scan, walks or cached folders', () => {
  assert.deepEqual(plain(D.initial()), { discover: null, driveDiscover: null, scanning: false, driveScanning: false,
    walks: {}, discoverCounts: {}, datasets: {}, repos: {}, worktrees: {}, childFolders: {}, childrenAsked: {} });
});

test('a scan clears the folder error and asks the daemon, unless it is offline', () => {
  const online = run({}, { type: 'scan', online: true });
  assert.equal(online.state.scanning, true);
  assert.deepEqual(online.effects, [{ type: 'error', surface: 'folderError', error: null },
    { type: 'send', message: { t: 'discover_start' } }]);
  const offline = run({}, { type: 'scan', online: false });
  assert.equal(offline.state.scanning, false);
  assert.deepEqual(sends(offline.effects), []);
});

test('a drive scan drops the last drive snapshot and names the volume', () => {
  const { state, effects } = run({ driveDiscover: { volume: 'old' } }, { type: 'scan-drive', uuid: 'usb', online: true });
  assert.equal(state.driveDiscover, null);
  assert.equal(state.driveScanning, true);
  assert.deepEqual(effects, [{ type: 'error', surface: 'driveError', error: null },
    { type: 'send', message: { t: 'discover_start', volume: 'usb' } }]);
});

test('a scan result lands on the folders step or the drive dialog and ends its scan', () => {
  const home = run({ scanning: true }, message({ t: 'discover_result', roots: [], folders: [] }));
  assert.equal(home.state.scanning, false);
  assert.deepEqual(plain(home.state.discover), { t: 'discover_result', roots: [], folders: [] });
  assert.deepEqual(errors(home.effects), [{ type: 'error', surface: 'folderError', error: null }]);
  const drive = run({ scanning: true, driveScanning: true },
    message({ t: 'discover_result', volume: 'usb', roots: [], folders: [] }));
  assert.equal(drive.state.driveScanning, false);
  assert.equal(drive.state.scanning, true);
  assert.equal(drive.state.discover, null);
  assert.equal(drive.state.driveDiscover.volume, 'usb');
  assert.deepEqual(errors(drive.effects), [{ type: 'error', surface: 'driveError', error: null }]);
});

test('counts merge batches and retain errors and dataset evidence', () => {
  const { state } = run({},
    counts({ root: '/h', counts: { '/h/a': { text: 2 } }, done: false }),
    counts({ root: '/h', counts: { '/h/b': { pdf: 1 } }, done: true,
      seconds: 0.4, error: 'fd failed', datasets: [{ path: '/h/a/data', kind: 'image' }] }));
  assert.deepEqual(plain(state.discoverCounts), { '/h/a': { text: 2 }, '/h/b': { pdf: 1 } });
  assert.deepEqual(plain(state.walks['/h']), { done: true, seconds: 0.4, error: 'fd failed',
    failure: { code: 'unknown', title: 'fd failed', detail: '' } });
  assert.equal(state.datasets['/h/a/data'].kind, 'image');
});

test('a counts batch without a root or counts changes nothing', () => {
  const start = D.initial();
  assert.equal(D.reduce(start, counts({ counts: {} })).state, start);
  assert.equal(D.reduce(start, counts({ root: '/h' })).state, start);
});

test('a batch replaces only the maps it carries, so unchanged maps keep their identity', () => {
  const first = run({}, counts({ root: '/h', counts: {}, done: false, datasets: [{ path: '/h/d' }] })).state;
  const next = D.reduce(first, counts({ root: '/h', counts: { '/h/a': { text: 1 } }, done: false })).state;
  assert.equal(next.datasets, first.datasets);
  assert.equal(next.worktrees, first.worktrees);
  assert.equal(next.childFolders, first.childFolders);
  assert.notEqual(next.discoverCounts, first.discoverCounts);
  assert.notEqual(next.walks, first.walks);
});

test('children requests send once and an offline request can be retried', () => {
  let { state, effects } = run({}, { type: 'children', path: '/h/a', online: false });
  assert.deepEqual(sends(effects), []);
  assert.deepEqual(plain(state.childrenAsked), {});
  ({ state, effects } = run(state, { type: 'children', path: '/h/a', online: true },
    { type: 'children', path: '/h/a', online: true }));
  assert.deepEqual(sends(effects), [{ t: 'discover_children', path: '/h/a' }]);
  ({ state, effects } = run(state, children({ path: '/h/a', dirs: [], volume: 'u' }),
    { type: 'children', path: '/h/a', online: true }));
  assert.deepEqual(plain(state.childFolders['/h/a']), { dirs: [], volume: 'u', error: '' });
  assert.deepEqual(plain(state.childrenAsked), {});
  assert.deepEqual(sends(effects), []);
  assert.deepEqual(effects, [{ type: 'children', path: '/h/a' }]);
});

test('an unreadable children reply can be retried', () => {
  const { effects } = run({}, { type: 'children', path: '/h/a', online: true },
    children({ path: '/h/a', dirs: [], error: 'Permission denied' }),
    { type: 'children', path: '/h/a', online: true });
  assert.equal(sends(effects).length, 2);
});

test('a fresh walk clears stale counts and dataset proposals only under its root', () => {
  const { state } = run({ discoverCounts: { '/h/a': { text: 9 }, '/m/b': { text: 1 } },
    datasets: { '/h/a': { path: '/h/a' }, '/m/b': { path: '/m/b' } } },
  counts({ root: '/h', counts: {}, done: false, reset: true }));
  assert.deepEqual(plain(state.discoverCounts), { '/m/b': { text: 1 } });
  assert.deepEqual(Object.keys(state.datasets), ['/m/b']);
});

test('stopping finishes the walks and clears both scans so the next scan asks again', () => {
  const { state, effects } = run({ scanning: true, driveScanning: true,
    walks: { '/h': { done: false, seconds: null, error: '' } } },
  { type: 'stop', online: true }, { type: 'scan', online: true });
  assert.equal(state.driveScanning, false);
  assert.equal(state.walks['/h'].done, true);
  assert.equal(state.scanning, true);
  assert.deepEqual(sends(effects), [{ t: 'discover_stop' }, { t: 'discover_start' }]);
});

test('stopping discovery forgets children requests the daemon will not answer', () => {
  const { effects } = run({}, { type: 'children', path: '/h/a', online: true }, { type: 'stop', online: true },
    { type: 'children', path: '/h/a', online: true });
  assert.equal(sends(effects).length, 3);
});

test('a delayed children snapshot preserves newer streamed counts', () => {
  const { state } = run({}, counts({ root: '/h', counts: { '/h/a': { text: 9 } }, done: true }),
    children({ path: '/h', dirs: [{ path: '/h/a', counts: { text: 3 } }], volume: 'u' }));
  assert.equal(state.discoverCounts['/h/a'].text, 9);
});

test('socket loss finishes open walks and preserves completed walks', () => {
  const { state } = run({ scanning: true, driveScanning: true, childrenAsked: { '/h/a': true },
    walks: { '/h': { done: false, seconds: null, error: '' }, '/m': { done: true, seconds: 1, error: '' } } },
  { type: 'offline' });
  assert.deepEqual(plain(state.walks['/h']), { done: true, seconds: null,
    error: 'The omafind service is not running.', failure: {
      code: 'daemon-offline', title: 'The omafind service is not running.',
      detail: 'It did not answer on its socket. Press Retry to start it.', fix: { kind: 'retry' },
    } });
  assert.deepEqual(plain(state.walks['/m']), { done: true, seconds: 1, error: '' });
  assert.equal(state.scanning, false);
  assert.equal(state.driveScanning, false);
  assert.deepEqual(plain(state.childrenAsked), {});
});

test('dataset evidence from a child reply joins streamed proposals', () => {
  const { state } = run({}, children({ path: '/h/Photos', dirs: [
    { path: '/h/Photos/data', rule: 'dataset', evidence: { kind: 'image', files: 300, named: 100 } },
  ] }));
  assert.deepEqual(plain(state.datasets['/h/Photos/data']),
    { path: '/h/Photos/data', kind: 'image', files: 300, named: 100 });
});

test('a fresh walk keeps the volume of a folder added outside every root', () => {
  const { state } = run({}, children({ path: '/srv/data', dirs: [], volume: 'u' }),
    counts({ root: '/srv/data', counts: {}, done: false, reset: true }));
  assert.equal(state.childFolders['/srv/data'].volume, 'u');
});

test('the final walk batch records repos and worktrees and a reset clears them', () => {
  let { state } = run({}, counts({ root: '/h', counts: {}, done: true, datasets: [],
    repos: ['/h/p/main'], worktrees: ['/h/p/wt'] }));
  assert.deepEqual(Object.keys(state.repos), ['/h/p/main']);
  assert.deepEqual(Object.keys(state.worktrees), ['/h/p/wt']);
  ({ state } = run(state, counts({ root: '/h', counts: {}, reset: true })));
  assert.deepEqual(Object.keys(state.repos), []);
});

test('a rescan forgets the finished walk so its next finish sorts the folders again', () => {
  const { state } = run({}, counts({ root: '/h', counts: { '/h/a': { text: 2 } }, done: true }),
    counts({ root: '/m', counts: { '/m/b': { pdf: 1 } }, done: true }),
    message({ t: 'discover_result', roots: [{ path: '/h' }], folders: [] }));
  assert.equal(state.walks['/h'], undefined);
  assert.equal(state.walks['/m'].done, true);
});

test('a home walk reset keeps the replayed walk of a drive mounted inside home', () => {
  let { state } = run({}, counts({ root: '/h/disk', counts: { '/h/disk/p': { image: 3 } }, done: true }),
    counts({ root: '/h', counts: { '/h/a': { text: 2 } }, done: false, reset: true }));
  assert.equal(state.walks['/h/disk'].done, true);
  assert.deepEqual(plain(state.discoverCounts['/h/disk/p']), { image: 3 });
  ({ state } = run(state, counts({ root: '/h', counts: {}, done: false, reset: true })));
  assert.equal(state.discoverCounts['/h/a'], undefined);
});

test('walk and child errors keep one fact and give the folder step the object', () => {
  const { state, effects } = run({}, counts({ root: '/h', counts: {}, done: true, error: scanFailed }),
    children({ path: '/h/a', dirs: [], error: scanFailed }),
    children({ path: '/h/b', dirs: [], error: 'Permission denied' }));
  assert.equal(state.walks['/h'].error, 'Pictures could not be scanned.');
  assert.deepEqual(errors(effects), [{ type: 'error', surface: 'folderError', error: scanFailed }]);
  assert.equal(state.childFolders['/h/a'].error, 'Pictures could not be scanned.');
  assert.equal(state.childFolders['/h/b'].error, 'Permission denied');
});

test('drive walk errors stay on the walk instead of the folders step', () => {
  for (const values of [
    { driveScanning: true },
    { driveDiscover: { volume: 'usb', roots: [{ path: '/m', volume: 'usb' }] } },
    { discover: { roots: [{ path: '/h', volume: null }, { path: '/m', volume: 'usb' }] } },
    { childFolders: { '/m': { dirs: [], volume: 'usb', error: '' } } },
  ]) {
    const { state, effects } = run(values, counts({ root: '/m', counts: {}, done: true, error: scanFailed }));
    assert.deepEqual(errors(effects), []);
    assert.deepEqual(plain(state.walks['/m'].failure), scanFailed);
    assert.equal(state.walks['/m'].error, scanFailed.title);
  }
});

test('a home walk error still reaches folders after a drive scan', () => {
  const { effects } = run({ driveDiscover: { volume: 'usb', roots: [{ path: '/m', volume: 'usb' }] } },
    counts({ root: '/h', counts: {}, done: true, error: scanFailed }));
  assert.deepEqual(errors(effects), [{ type: 'error', surface: 'folderError', error: scanFailed }]);
});

test('a known home root keeps its folder error while a drive scan is pending', () => {
  const { effects } = run({ driveScanning: true,
    discover: { roots: [{ path: '/h', volume: null }, { path: '/m', volume: 'usb' }] } },
  counts({ root: '/h', counts: {}, done: true, error: scanFailed }));
  assert.deepEqual(errors(effects), [{ type: 'error', surface: 'folderError', error: scanFailed }]);
});

test('a failed request ends the scan it belongs to and forgets pending children', () => {
  assert.equal(run({ scanning: true }, { type: 'failed', for: 'discover_start' }).state.scanning, false);
  const drive = run({ scanning: true, driveScanning: true }, { type: 'failed', for: 'discover_start' }).state;
  assert.equal(drive.driveScanning, false);
  assert.equal(drive.scanning, true);
  const asked = run({ childrenAsked: { '/h/a': true } }, { type: 'failed', for: 'discover_children' }).state;
  assert.deepEqual(plain(asked.childrenAsked), {});
  const start = freeze(D.initial());
  assert.equal(D.reduce(start, { type: 'failed', for: 'index_start' }).state, start);
});
