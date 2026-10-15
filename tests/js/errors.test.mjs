import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
import { plain, freeze } from './fixtures.mjs';
const e = load('errors.js');

const missing = freeze({ code: 'build-missing-packages', title: 'The search engine could not be built.',
  detail: 'Missing build packages: vulkan-headers. Install them, then press Retry.',
  fix: { kind: 'install', packages: ['vulkan-headers'] },
  log: '/home/u/.local/share/omafind/cache/logs/build-runtime.log' });

test('wrap keeps error objects and turns an older bare reason into an unknown error', () => {
  assert.equal(e.wrap(missing), missing);
  assert.deepEqual(plain(e.wrap('Embedding server failed to start')),
    { code: 'unknown', title: 'Embedding server failed to start', detail: '' });
  assert.deepEqual(plain(e.wrap('  Cannot read binds.\n')), { code: 'unknown', title: 'Cannot read binds.', detail: '' });
  for (const empty of [null, undefined, '', '   ', 0, false]) assert.equal(e.wrap(empty), null);
});

test('from takes the error out of any daemon message and drops its routing fields', () => {
  const { t, ...fields } = { t: 'error', ...missing };
  assert.deepEqual(plain(e.from({ t: 'error', for: 'runtime_install', ...fields })), plain(missing));
  assert.deepEqual(plain(e.from({ t: 'error', seq: 4, code: 'no-index', title: 'Nothing is indexed yet.',
    detail: 'Open setup and start the first index.' })),
    { code: 'no-index', title: 'Nothing is indexed yet.', detail: 'Open setup and start the first index.' });
  assert.deepEqual(plain(e.from({ t: 'open_failed', id: 'pdf:1', error: { code: 'file-missing',
    title: 'a.pdf is missing.', detail: 'It was moved or deleted after it was indexed.' } })),
    { code: 'file-missing', title: 'a.pdf is missing.', detail: 'It was moved or deleted after it was indexed.' });
  assert.deepEqual(plain(e.from({ t: 'runtime_progress', state: 'failed', error: null, reason: 'exit 1' })),
    { code: 'unknown', title: 'exit 1', detail: '' });
  assert.deepEqual(plain(e.from({ t: 'warm_failed', error: 'Vulkan device lost' })),
    { code: 'unknown', title: 'Vulkan device lost', detail: '' });
  assert.equal(e.from({ t: 'discover_children', path: '/h', dirs: [], error: null }), null);
  for (const empty of [null, undefined, '']) assert.equal(e.from(empty), null);
});

test('degraded and paused codes are yellow and every other code is red', () => {
  for (const code of ['server-starting', 'embedding-unavailable', 'disk-low', 'index-running', 'update-running'])
    assert.equal(e.tone(code), 'warn', code);
  for (const code of ['build-missing-packages', 'build-failed', 'server-start-failed', 'index-exited',
    'tool-missing', 'daemon-offline', 'unknown', '', undefined])
    assert.equal(e.tone(code), 'urgent', String(code));
});

test('an install fix becomes one pacman line', () => {
  assert.equal(e.installCommand(missing.fix), 'sudo pacman -S --needed vulkan-headers');
  assert.equal(e.installCommand({ kind: 'install', packages: ['fd', 'ripgrep'] }), 'sudo pacman -S --needed fd ripgrep');
  for (const fix of [{ kind: 'retry' }, { kind: 'install', packages: [] }, null, undefined])
    assert.equal(e.installCommand(fix), '');
});

test('fix helpers read the fix kind', () => {
  assert.equal(e.hasInstall(missing), true);
  assert.equal(e.hasRetry(missing), false);
  assert.equal(e.hasRetry({ code: 'build-failed', fix: { kind: 'retry' } }), true);
  assert.equal(e.hasInstall({ code: 'tools-missing', fix: { kind: 'install', packages: [] } }), false);
  for (const none of [null, undefined, { code: 'no-index', title: 'Nothing is indexed yet.', detail: '' }]) {
    assert.equal(e.hasInstall(none), false);
    assert.equal(e.hasRetry(none), false);
  }
});

test('the offline error offers Retry and links the startup log only when it exists', () => {
  assert.deepEqual(plain(e.offline()), { code: 'daemon-offline', title: 'The omafind service is not running.',
    detail: 'It did not answer on its socket. Press Retry to start it.', fix: { kind: 'retry' } });
  assert.equal(e.offline('/d/cache/logs/omafindd-start.log').log, '/d/cache/logs/omafindd-start.log');
  assert.equal(e.hasRetry(e.offline()), true);
});

test('copy written in the UI follows the copy rules', () => {
  const banned = /[–—!]|\b(seamless|leverage|robust|comprehensive|delve|showcase|vibrant|crucial|pivotal|streamline|empower|foster|testament|landscape|tapestry|journey|unlock|elevate)\b|bin\/omafind|systemctl|journalctl/i;
  const { title, detail } = e.offline();
  for (const line of [title, detail]) {
    assert.match(line, /\.$/);
    assert.doesNotMatch(line, banned);
  }
});
