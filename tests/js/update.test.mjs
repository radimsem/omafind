import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
import { freeze, plain } from './fixtures.mjs';

const { initial, reduce } = load('Update.js');

function run(events, state = initial()) {
  const effects = [];
  for (const event of events) {
    const result = reduce(freeze(state), freeze(event));
    state = result.state;
    effects.push(...result.effects);
  }
  return { state: plain(state), effects: plain(effects) };
}

test('initial update state waits for both builds', () => {
  assert.deepEqual(plain(initial()),
    { local: null, daemon: null, phase: 'idle', tried: null, error: '', failure: null });
  assert.deepEqual(run([{ type: 'local', build: '0.1.0+aaa' }]).effects, []);
  assert.deepEqual(run([{ type: 'daemon', build: '0.1.0+aaa' }]).effects, []);
});

test('matching builds run nothing', () => {
  const result = run([{ type: 'local', build: '0.1.0+aaa' }, { type: 'daemon', build: '0.1.0+aaa' }]);
  assert.equal(result.state.phase, 'idle');
  assert.deepEqual(result.effects, []);
});

test('a daemon on another build reruns setup once, in either arrival order', () => {
  for (const events of [
    [{ type: 'local', build: '0.1.0+bbb' }, { type: 'daemon', build: '0.1.0+aaa' }],
    [{ type: 'daemon', build: '0.1.0+aaa' }, { type: 'local', build: '0.1.0+bbb' }],
  ]) {
    const result = run([...events, { type: 'daemon', build: '0.1.0+aaa' }]);
    assert.equal(result.state.phase, 'updating');
    assert.equal(result.state.tried, '0.1.0+bbb');
    assert.deepEqual(result.effects, [{ type: 'setup' }]);
  }
});

test('a daemon that predates the build field counts as another build', () => {
  const result = run([{ type: 'local', build: '0.1.0+bbb' }, { type: 'daemon', build: '' }]);
  assert.deepEqual(result.effects, [{ type: 'setup' }]);
});

test('a finished setup returns to idle and the new daemon build matches', () => {
  const result = run([{ type: 'local', build: 'b' }, { type: 'daemon', build: 'a' },
    { type: 'setup-exited', ok: true, line: '' }, { type: 'daemon', build: 'b' }]);
  assert.equal(result.state.phase, 'idle');
  assert.deepEqual(result.effects, [{ type: 'setup' }]);
});

test('setup is not rerun for the same build after it finished', () => {
  const result = run([{ type: 'local', build: 'b' }, { type: 'daemon', build: 'a' },
    { type: 'setup-exited', ok: true, line: '' }, { type: 'daemon', build: 'a' },
    { type: 'daemon', build: 'a' }]);
  assert.equal(result.state.phase, 'idle');
  assert.deepEqual(result.effects, [{ type: 'setup' }]);
});

test('a failed setup keeps its line and does not loop', () => {
  const result = run([{ type: 'local', build: 'b' }, { type: 'daemon', build: 'a' },
    { type: 'setup-exited', ok: false, line: 'uv sync failed' }, { type: 'daemon', build: 'a' },
    { type: 'daemon', build: '' }]);
  assert.equal(result.state.phase, 'failed');
  assert.equal(result.state.error, 'uv sync failed');
  assert.deepEqual(result.effects, [{ type: 'setup' }]);
});

test('a failed setup without output still reports a line', () => {
  const result = run([{ type: 'local', build: 'b' }, { type: 'daemon', build: 'a' },
    { type: 'setup-exited', ok: false, line: '' }]);
  assert.equal(result.state.error, 'bin/omafind setup failed');
});

test('retry reruns setup only after a failure', () => {
  assert.deepEqual(run([{ type: 'retry' }]).effects, []);
  const result = run([{ type: 'local', build: 'b' }, { type: 'daemon', build: 'a' },
    { type: 'setup-exited', ok: false, line: 'x' }, { type: 'retry' }]);
  assert.equal(result.state.phase, 'updating');
  assert.equal(result.state.error, '');
  assert.deepEqual(result.effects, [{ type: 'setup' }, { type: 'setup' }]);
});

test('a newer plugin build gets its own setup run', () => {
  const result = run([{ type: 'local', build: 'b' }, { type: 'daemon', build: 'a' },
    { type: 'setup-exited', ok: false, line: 'x' }, { type: 'local', build: 'c' }]);
  assert.equal(result.state.phase, 'updating');
  assert.equal(result.state.tried, 'c');
  assert.deepEqual(result.effects, [{ type: 'setup' }, { type: 'setup' }]);
});

test('a setup exit outside an update changes nothing', () => {
  const result = run([{ type: 'setup-exited', ok: false, line: 'x' }]);
  assert.deepEqual(result.state, plain(initial()));
});

test('a daemon that reaches the local build clears a failure', () => {
  const result = run([{ type: 'local', build: 'b' }, { type: 'daemon', build: 'a' },
    { type: 'setup-exited', ok: false, line: 'x' }, { type: 'daemon', build: 'b' }]);
  assert.equal(result.state.phase, 'idle');
  assert.equal(result.state.error, '');
});

test('a stale or missing venv reruns setup once when the daemon never answers', () => {
  for (const venv of ['stale', 'missing']) {
    const result = run([{ type: 'local', build: 'b' }, { type: 'venv', state: venv },
      { type: 'venv', state: venv }]);
    assert.equal(result.state.phase, 'updating');
    assert.deepEqual(result.effects, [{ type: 'setup' }]);
  }
});

test('a ready or unknown venv, or no local build, runs nothing', () => {
  assert.deepEqual(run([{ type: 'local', build: 'b' }, { type: 'venv', state: 'ready' }]).effects, []);
  assert.deepEqual(run([{ type: 'local', build: 'b' }, { type: 'venv', state: 'unknown' }]).effects, []);
  assert.deepEqual(run([{ type: 'venv', state: 'stale' }]).effects, []);
});

test('the banner is an error object for each update phase', () => {
  const { banner } = load('Update.js');
  assert.equal(banner(initial()), null);
  assert.deepEqual(plain(banner({ ...initial(), phase: 'updating' })), { code: 'update-running',
    title: 'omafindd is updating to match the installed plugin.', detail: 'Search returns when it restarts.' });
  assert.deepEqual(plain(banner({ ...initial(), phase: 'failed', error: 'uv sync failed.' })), {
    code: 'update-failed', title: 'omafindd did not update.',
    detail: 'uv sync failed. Press Retry to try again.', fix: { kind: 'retry' } });
});

test('a running update is a yellow card and a failed one is red', () => {
  const { tone } = load('errors.js');
  assert.equal(tone('update-running'), 'warn');
  assert.equal(tone('update-failed'), 'urgent');
});


const failure = freeze({ code: 'tools-missing', title: 'Some tools omafind needs are missing.',
  detail: 'Missing: fd. Install them, then press Retry.', fix: { kind: 'install', packages: ['fd'] },
  log: '/d/setup.log' });

function failedUpdate() {
  return run([{ type: 'local', build: 'b' }, { type: 'daemon', build: 'a' },
    { type: 'setup-exited', ok: false, line: 'sudo pacman -S --needed fd', error: failure }]).state;
}

test('a failed update keeps the error object across daemon events without retrying', () => {
  const result = run([{ type: 'daemon', build: 'a' }, { type: 'venv', state: 'stale' }], failedUpdate());
  assert.deepEqual(result.state.failure, plain(failure));
  assert.deepEqual(result.effects, []);
  assert.deepEqual(plain(load('Update.js').banner(result.state)), { code: 'update-failed',
    title: 'omafindd did not update.', detail: failure.title + ' ' + failure.detail,
    fix: plain(failure.fix), log: failure.log });
});

test('the update banner keeps only an install fix and trims the failure copy', () => {
  const { banner } = load('Update.js');
  for (const fix of [undefined, { kind: 'retry' }]) {
    assert.deepEqual(plain(banner({ ...failedUpdate(), failure: { title: 'Setup failed.', detail: '', fix } })),
      { code: 'update-failed', title: 'omafindd did not update.', detail: 'Setup failed.', fix: { kind: 'retry' } });
  }
});

for (const [name, event] of [
  ['Retry', { type: 'retry' }], ['a new build', { type: 'local', build: 'c' }],
  ['a matching daemon', { type: 'daemon', build: 'b' }],
]) {
  test(name + ' clears both update errors', () => {
    const { state } = run([event], failedUpdate());
    assert.equal(state.error, '');
    assert.equal(state.failure, null);
  });
}

test('a successful setup exit clears both update errors', () => {
  const { state } = run([{ type: 'setup-exited', ok: true }], { ...failedUpdate(), phase: 'updating' });
  assert.equal(state.failure, null);
  assert.equal(state.error, '');
});
