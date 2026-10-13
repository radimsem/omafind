import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
import { freeze, plain } from './fixtures.mjs';

const drive = freeze({t: 'volume', uuid: '6BFF-B220', label: 'Photos2024', fs: 'exfat',
  size: 1800000000000, mount: '/run/media/radimsem/Photos2024', online: true, known: false});
const volumes = () => load('format.js', 'volumes.js');

test('unknown drive raises the New drive toast', () => {
  const v = volumes();
  const state = freeze(v.initial());
  assert.deepEqual(plain(state), {toasts: [], drives: {}, reconcile: null, disk: null, ignored: []});
  const result = v.reduce(state, freeze({type: 'volume', message: drive, now: 100}));
  assert.equal(result.state.toasts.length, 1);
  const toast = result.state.toasts[0];
  assert.equal(typeof toast.id, 'string');
  assert.deepEqual(plain(toast), {id: toast.id, kind: 'drive', uuid: '6BFF-B220',
    title: 'New drive found',
    body: 'Photos2024 (exFAT, 1.8 TB) is connected. Scan it for photos, videos and documents to search?',
    buttons: [{label: 'Not this drive', choice: 'ignore'}, {label: 'Scan', choice: 'scan'}], until: null});
  assert.deepEqual(plain(result.effects), []);
  assert.deepEqual(plain(result.state.drives['6BFF-B220']), plain(drive));
  assert.equal(state.toasts.length, 0);
  const replay = v.reduce(freeze(result.state), {type: 'volume', message: drive, now: 200});
  assert.equal(replay.state.toasts.length, 1);
  assert.equal(replay.state.toasts[0].id, toast.id);
});

test('Not this drive persists ignoredVolumes and suppresses the toast', () => {
  const v = volumes();
  let state = v.reduce(v.initial(), {type: 'settings', ignoredVolumes: ['backup']}).state;
  state = v.reduce(state, {type: 'volume', message: drive, now: 100}).state;
  const result = v.reduce(freeze(state), {type: 'decide', uuid: drive.uuid, choice: 'ignore', now: 200});
  assert.deepEqual(plain(result.state.ignored), ['backup', '6BFF-B220']);
  assert.deepEqual(plain(result.state.toasts), []);
  assert.deepEqual(plain(result.effects), [
    {type: 'send', message: {t: 'drive_decision', uuid: '6BFF-B220', choice: 'ignore'}},
    {type: 'persist', changes: {ignoredVolumes: ['backup', '6BFF-B220']}}
  ]);
  const replay = v.reduce(freeze(result.state), {type: 'volume', message: drive, now: 300});
  assert.equal(replay.state.toasts.length, 0);
  const repeat = v.reduce(replay.state, {type: 'decide', uuid: drive.uuid, choice: 'ignore', now: 400});
  assert.deepEqual(plain(repeat.state.ignored), ['backup', '6BFF-B220']);
  assert.deepEqual(plain(state.ignored), ['backup']);
});

test('Scan sends the decision and summons this volume without persisting an ignore', () => {
  const v = volumes();
  const state = v.reduce(v.initial(), {type: 'volume', message: drive, now: 100}).state;
  const result = v.reduce(freeze(state), {type: 'decide', uuid: drive.uuid, choice: 'scan', now: 200});
  assert.deepEqual(plain(result.state.toasts), []);
  assert.deepEqual(plain(result.state.ignored), []);
  assert.deepEqual(plain(result.effects), [
    {type: 'send', message: {t: 'drive_decision', uuid: '6BFF-B220', choice: 'scan'}},
    {type: 'summon', payload: {view: 'drive', volume: '6BFF-B220'}}
  ]);
  assert.equal(state.toasts.length, 1);
});

test('returning drive shows Checking for changes then Photos2024 is up to date', () => {
  const v = volumes();
  const returned = v.reduce(v.initial(), {type: 'volume', message: {...drive, known: true}, now: 100});
  assert.deepEqual(plain(returned.state.toasts[0]), {id: returned.state.toasts[0].id,
    kind: 'returned', uuid: '6BFF-B220', title: 'Photos2024 connected', body: 'Checking for changes',
    buttons: [], until: 3000});
  assert.deepEqual(plain(returned.state.reconcile), {uuid: '6BFF-B220', label: 'Photos2024',
    done: 0, total: 0, done_at: null});
  assert.deepEqual(plain(v.footer(returned.state, 100)), {text: 'Checking Photos2024 for changes', fraction: 0});
  const checking = v.reduce(freeze(returned.state), {type: 'reconcile',
    message: {t: 'reconcile', uuid: drive.uuid, done: 120, total: 900}, now: 200});
  assert.deepEqual(plain(v.footer(checking.state, 200)),
    {text: 'Checking Photos2024 for changes', fraction: 120 / 900});
  assert.deepEqual(plain(checking.effects), []);
  const complete = v.reduce(freeze(checking.state), {type: 'reconcile',
    message: {t: 'reconcile', uuid: drive.uuid, done: 900, total: 900}, now: 500});
  assert.deepEqual(plain(v.footer(complete.state, 1749)), {text: 'Photos2024 is up to date', fraction: 1});
  assert.equal(v.footer(complete.state, 1750), null);
  assert.equal(complete.state.reconcile.done_at, 500);
  assert.deepEqual(plain(complete.effects), [{type: 'research'}]);
  const duplicate = v.reduce(freeze(complete.state), {type: 'reconcile',
    message: {t: 'reconcile', uuid: drive.uuid, done: 900, total: 900}, now: 600});
  assert.equal(duplicate.state.reconcile.done_at, 600);
  assert.deepEqual(plain(duplicate.effects), [{type: 'research'}]);
});

test('empty reconciliation completes at time zero and can start again on return', () => {
  const v = volumes();
  const returned = v.reduce(v.initial(), {type: 'volume', message: {...drive, known: true}, now: 0}).state;
  const result = v.reduce(freeze(returned), {type: 'reconcile',
    message: {uuid: drive.uuid, done: 0, total: 0}, now: 0});
  assert.deepEqual(plain(v.footer(result.state, 0)), {text: 'Photos2024 is up to date', fraction: 1});
  assert.deepEqual(plain(result.effects), [{type: 'research'}]);
  assert.equal(v.footer(result.state, 1250), null);
  const again = v.reduce(result.state, {type: 'volume', message: {...drive, known: true}, now: 2000});
  assert.deepEqual(plain(v.footer(again.state, 2000)), {text: 'Checking Photos2024 for changes', fraction: 0});
});

test('gone drive removes its pending prompt and clears its reconciliation', () => {
  const v = volumes();
  let state = v.reduce(v.initial(), {type: 'volume', message: drive, now: 100}).state;
  state = v.reduce(state, {type: 'volume', message: {...drive, uuid: 'backup', label: 'Backup'}, now: 200}).state;
  const gone = v.reduce(freeze(state), {type: 'volume', message: {...drive, known: true, online: false}, now: 300});
  assert.equal(gone.state.toasts.some(toast => toast.kind === 'drive' && toast.uuid === drive.uuid), false);
  assert.equal(gone.state.toasts.some(toast => toast.kind === 'drive' && toast.uuid === 'backup'), true);
  const toast = gone.state.toasts.find(toast => toast.kind === 'gone');
  assert.deepEqual(plain(toast), {id: toast.id, kind: 'gone', uuid: '6BFF-B220',
    title: 'Photos2024 disconnected', body: 'Its files stay searchable.', buttons: [], until: 3200});
  assert.equal(gone.state.drives[drive.uuid].online, false);
  const returned = v.reduce(gone.state, {type: 'volume', message: {...drive, known: true}, now: 500}).state;
  const disconnected = v.reduce(freeze(returned), {type: 'volume',
    message: {...drive, known: true, online: false}, now: 600});
  assert.equal(v.footer(disconnected.state, 600), null);
});

test('tick expires feedback toasts at 2900 ms and preserves an undecided drive', () => {
  const v = volumes();
  let state = v.reduce(v.initial(), {type: 'volume', message: drive, now: 100}).state;
  state = v.reduce(state, {type: 'volume', message: {...drive, uuid: 'backup', known: true}, now: 100}).state;
  state = v.reduce(state, {type: 'volume', message: {...drive, uuid: 'gone', known: true, online: false}, now: 100}).state;
  assert.equal(v.reduce(freeze(state), {type: 'tick', now: 2999}).state.toasts.length, 3);
  const expired = v.reduce(freeze(state), {type: 'tick', now: 3000});
  assert.deepEqual(plain(expired.state.toasts.map(toast => toast.kind)), ['drive']);
  assert.deepEqual(plain(expired.effects), []);
});

test('dismiss removes only the selected toast without a drive decision', () => {
  const v = volumes();
  let state = v.reduce(v.initial(), {type: 'volume', message: drive, now: 100}).state;
  state = v.reduce(state, {type: 'volume', message: {...drive, uuid: 'backup'}, now: 100}).state;
  const result = v.reduce(freeze(state), {type: 'dismiss', id: state.toasts[0].id});
  assert.deepEqual(plain(result.state.toasts.map(toast => toast.uuid)), ['backup']);
  assert.deepEqual(plain(result.effects), []);
});

test('settings replace ignored UUIDs and suppress pending prompts for those drives', () => {
  const v = volumes();
  let state = v.reduce(v.initial(), {type: 'settings', ignoredVolumes: ['backup']}).state;
  state = v.reduce(state, {type: 'volume', message: drive, now: 100}).state;
  const ignored = freeze([drive.uuid]);
  const result = v.reduce(freeze(state), {type: 'settings', ignoredVolumes: ignored});
  assert.deepEqual(plain(result.state.ignored), ['6BFF-B220']);
  assert.equal(result.state.toasts.length, 0);
  assert.notEqual(result.state.ignored, ignored);
  const reallowed = v.reduce(result.state, {type: 'settings', ignoredVolumes: []}).state;
  assert.equal(v.reduce(reallowed, {type: 'volume', message: drive, now: 200}).state.toasts.length, 1);
});

test('paused shows the disk banner and resumed clears it', () => {
  const v = volumes();
  assert.equal(v.diskBanner(v.initial()), null);
  const result = v.reduce(freeze(v.initial()), {type: 'paused',
    message: freeze({t: 'paused', reason: 'disk', free_gb: 1.4, need_gb: 2})});
  assert.deepEqual(plain(result.state.disk), {free_gb: 1.4, need_gb: 2});
  assert.deepEqual(plain(v.diskBanner(result.state)), {title: 'Indexing paused',
    tokens: [{k: 'free', v: '1.4 GB'}, {k: 'needed', v: '2 GB'}],
    text: 'Free some disk space and indexing resumes.'});
  const resumed = v.reduce(freeze(result.state), {type: 'resumed'});
  assert.equal(resumed.state.disk, null);
  assert.equal(v.diskBanner(resumed.state), null);
  assert.deepEqual(plain(resumed.effects), []);
});

test('fsName uses display casing without changing unknown filesystems', () => {
  const v = volumes();
  for (const [fs, expected] of [['exfat', 'exFAT'], ['vfat', 'FAT32'], ['ntfs', 'NTFS'],
    ['ext4', 'ext4'], ['btrfs', 'Btrfs'], ['xfs', 'xfs'], ['constructor', 'constructor']]) {
    assert.equal(v.fsName(fs), expected);
  }
});

test('sizeText uses decimal units and one decimal below 100', () => {
  const v = volumes();
  for (const [bytes, expected] of [[1.8e12, '1.8 TB'], [2e9, '2.0 GB'], [99.4e9, '99.4 GB'],
    [100e9, '100 GB'], [256e6, '256 MB'], [18.25e6, '18.3 MB'], [999999, '1.0 MB']]) {
    assert.equal(v.sizeText(bytes), expected);
  }
});

test('driveLabel falls back to the mount basename then UUID', () => {
  const v = volumes();
  assert.equal(v.driveLabel(drive), 'Photos2024');
  assert.equal(v.driveLabel({...drive, label: '', mount: '/media/Camera/'}), 'Camera');
  assert.equal(v.driveLabel({...drive, label: '', mount: null}), '6BFF-B220');
  const result = v.reduce(v.initial(), {type: 'volume', message: {...drive, label: ''}, now: 0});
  assert.equal(result.state.toasts[0].body,
    'Photos2024 (exFAT, 1.8 TB) is connected. Scan it for photos, videos and documents to search?');
});

test('freshKeys uses result IDs and caps new rows at the indexed file increase', () => {
  const v = volumes();
  const prev = freeze([{id: 'image:1'}, {id: 'text:8'}]);
  const next = freeze([{id: 'image:2'}, {id: 'text:8'}, {id: 'image:3'}, {id: 'pdf:4'}, {id: 'image:1'}]);
  assert.deepEqual(plain(v.freshKeys(prev, next, 3880, 3882)), ['image:2', 'image:3']);
  assert.deepEqual(plain(v.freshKeys(prev, next, 3880, 3880)), []);
  assert.deepEqual(plain(v.freshKeys(prev, next, 3880, 3879)), []);
  assert.deepEqual(plain(v.freshKeys(prev, [{id: 'image:1'}], 3880, 3881)), []);
  assert.deepEqual(plain(v.freshKeys([], [{id: 'image:2'}, {id: 'image:2'}, {id: 'pdf:4'}], 0, 3)),
    ['image:2', 'pdf:4']);
  assert.deepEqual(plain(v.indexedToken(3880)), {k: 'indexed', v: '3,880'});
});

test('driveFacts keeps raw filesystem and the NewDrive fact order', () => {
  const v = volumes();
  assert.deepEqual(plain(v.driveFacts(drive, {seconds: 2.4})), [
    {k: 'mount', v: '/run/media/radimsem/Photos2024'}, {k: 'fs', v: 'exfat'}, {k: 'scan', v: '2.4 s'},
    {k: 'index', v: 'internal disk'}, {k: 'offline', v: 'results kept'}
  ]);
  assert.deepEqual(plain(v.driveFacts(drive, {running: true, seconds: 0.5})[2]), {k: 'scan', v: 'running'});
  assert.deepEqual(plain(v.driveFacts(drive, null)[2]), {k: 'scan', v: '—'});
});

test('relPath strips the full mount prefix without confusing sibling mounts', () => {
  const v = volumes();
  assert.equal(v.relPath('/run/media/radimsem/Photos2024/DCIM', drive.mount), '/DCIM');
  assert.equal(v.relPath(drive.mount, drive.mount), '/');
  assert.equal(v.relPath('/run/media/radimsem/Photos2024/DCIM', drive.mount + '/'), '/DCIM');
  assert.equal(v.relPath('/run/media/radimsem/Photos2024-copy/DCIM', drive.mount),
    '/run/media/radimsem/Photos2024-copy/DCIM');
  assert.equal(v.relPath('/DCIM', '/'), '/DCIM');
  assert.equal(v.relPath('/DCIM', null), '/DCIM');
});

test('dialogFooter uses only the selected volume counts and completion', () => {
  const v = volumes();
  const progress = freeze({t: 'progress', done: 800, total: 2000, running: true,
    volumes: {[drive.uuid]: {label: 'Photos2024', done: 612, total: 1209},
      backup: {label: 'Backup', done: 188, total: 791}}});
  assert.deepEqual(plain(v.dialogFooter(progress, drive.uuid, 'Photos2024')),
    {text: 'Indexing Photos2024', count: '612 of 1,209', fraction: 612 / 1209, done: false});
  const complete = {...progress, volumes: {[drive.uuid]: {label: 'Photos2024', done: 1209, total: 1209}}};
  assert.deepEqual(plain(v.dialogFooter(complete, drive.uuid, 'Photos2024')),
    {text: 'Indexed Photos2024', count: '1,209 of 1,209', fraction: 1, done: true});
  assert.deepEqual(plain(v.dialogFooter(progress, 'missing', 'Camera')),
    {text: 'Indexing Camera', count: '0 of 0', fraction: 0, done: false});
  assert.deepEqual(plain(v.dialogFooter(null, drive.uuid, 'Photos2024')),
    {text: 'Indexing Photos2024', count: '0 of 0', fraction: 0, done: false});
  assert.equal(v.dialogFooter({volumes: {[drive.uuid]: {done: 0, total: 0}}}, drive.uuid, 'Photos2024').done, true);
  assert.deepEqual(plain(v.dialogFooter({running: true, volumes: {[drive.uuid]: {done: 0, total: 0}}}, drive.uuid, 'Photos2024')),
    {text: 'Indexing Photos2024', count: '0 of 0', fraction: 0, done: false});
});
