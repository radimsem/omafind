import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';

const { normalize, merge } = load('Settings.js');
const plain = value => JSON.parse(JSON.stringify(value));

test('settings default to unfinished setup, automatic GPU and audio', () => {
  for (const entry of [undefined, null, [], 'bad', {}]) {
    assert.deepEqual(plain(normalize(entry)), { setupDone: false, gpu: 'auto', audio: true });
  }
});

test('settings preserve valid configured values', () => {
  assert.deepEqual(plain(normalize({ setupDone: true, gpu: 'never', audio: false })),
    { setupDone: true, gpu: 'never', audio: false });
});

test('settings clamp invalid values to defaults without coercion', () => {
  assert.deepEqual(plain(normalize({ setupDone: 'true', gpu: 'always', audio: 0 })),
    { setupDone: false, gpu: 'auto', audio: true });
});

test('merge preserves unknown keys including nested settings', () => {
  const entry = Object.freeze({ enabled: true, roots: [{ path: '/x', volume: 'v', excludes: [] }],
    audio: true, gpu: 'auto' });
  const changes = Object.freeze({ audio: false, setupDone: true, future: { mode: 'on' } });
  assert.deepEqual(plain(merge(entry, changes)), { enabled: true,
    roots: [{ path: '/x', volume: 'v', excludes: [] }], audio: false, gpu: 'auto',
    setupDone: true, future: { mode: 'on' } });
  assert.equal(entry.audio, true);
});

test('merge accepts absent entries and normalizes invalid known keys', () => {
  assert.deepEqual(plain(merge(null, { gpu: 'bad', audio: 'false' })),
    { setupDone: false, gpu: 'auto', audio: true });
  assert.deepEqual(plain(merge(undefined, undefined)),
    { setupDone: false, gpu: 'auto', audio: true });
});

test('merge keeps special unknown keys as own properties', () => {
  const result = merge(JSON.parse('{"__proto__":{"future":true}}'), {});
  assert.equal(Object.hasOwn(result, '__proto__'), true);
  assert.deepEqual(plain(result.__proto__), { future: true });
  assert.equal(result.future, undefined);
});
