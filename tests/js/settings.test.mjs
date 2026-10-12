import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';

const { normalize, merge } = load('Settings.js');
const plain = value => JSON.parse(JSON.stringify(value));

test('settings default to unfinished setup, automatic GPU and audio', () => {
  for (const entry of [undefined, null, [], 'bad', {}]) {
    assert.deepEqual(plain(normalize(entry)), { setupDone: false, gpu: 'auto', audio: true, roots: [], maxResults: 40, warmMinutes: 5 });
  }
});

test('settings preserve valid configured values', () => {
  assert.deepEqual(plain(normalize({ setupDone: true, gpu: 'never', audio: false, roots: [], maxResults: 40, warmMinutes: 5 })),
    { setupDone: true, gpu: 'never', audio: false, roots: [], maxResults: 40, warmMinutes: 5 });
});

test('settings clamp invalid values to defaults without coercion', () => {
  assert.deepEqual(plain(normalize({ setupDone: 'true', gpu: 'always', audio: 0 })),
    { setupDone: false, gpu: 'auto', audio: true, roots: [], maxResults: 40, warmMinutes: 5 });
});

test('merge preserves unknown keys including nested settings', () => {
  const entry = Object.freeze({ enabled: true, roots: [{ path: '/x', volume: 'v', excludes: [] }],
    audio: true, gpu: 'auto' });
  const changes = Object.freeze({ audio: false, setupDone: true, future: { mode: 'on' }, maxResults: 40, warmMinutes: 5 });
  assert.deepEqual(plain(merge(entry, changes)), { enabled: true,
    roots: [{ path: '/x', volume: 'v', excludes: [] }], audio: false, gpu: 'auto',
    setupDone: true, future: { mode: 'on' }, maxResults: 40, warmMinutes: 5 });
  assert.equal(entry.audio, true);
});

test('merge accepts absent entries and normalizes invalid known keys', () => {
  assert.deepEqual(plain(merge(null, { gpu: 'bad', audio: 'false' })),
    { setupDone: false, gpu: 'auto', audio: true, roots: [], maxResults: 40, warmMinutes: 5 });
  assert.deepEqual(plain(merge(undefined, undefined)),
    { setupDone: false, gpu: 'auto', audio: true, roots: [], maxResults: 40, warmMinutes: 5 });
});

test('merge keeps special unknown keys as own properties', () => {
  const result = merge(JSON.parse('{"__proto__":{"future":true}}'), {});
  assert.equal(Object.hasOwn(result, '__proto__'), true);
  assert.deepEqual(plain(result.__proto__), { future: true });
  assert.equal(result.future, undefined);
});

test('search settings clamp integer bounds without coercion', () => {
  assert.equal(normalize({maxResults: 1}).maxResults, 10);
  assert.equal(normalize({maxResults: 999}).maxResults, 200);
  assert.equal(normalize({maxResults: true}).maxResults, 40);
  assert.equal(normalize({warmMinutes: -1}).warmMinutes, 0);
  assert.equal(normalize({warmMinutes: 100}).warmMinutes, 60);
  assert.equal(normalize({warmMinutes: '2'}).warmMinutes, 5);
});

test('roots retain only valid path volume and excludes entries', () => {
  assert.deepEqual(plain(normalize({roots: [null, 'bad', {path: '/x', volume: 'v', excludes: ['/x/no']}]}).roots),
    [{path: '/x', volume: 'v', excludes: ['/x/no']}]);
});
