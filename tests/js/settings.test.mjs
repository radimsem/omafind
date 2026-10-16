import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';

const { normalize, merge } = load('Settings.js');
const plain = value => JSON.parse(JSON.stringify(value));

test('settings default to unfinished setup, automatic GPU and audio', () => {
  for (const entry of [undefined, null, [], 'bad', {}]) {
    assert.deepEqual(plain(normalize(entry)), { setupDone: false, gpu: 'auto', audio: true, roots: [], maxResults: 40, warmMinutes: 5, imageBudget: 140, shortcut: 'SUPER + E', ignoredVolumes: [] });
  }
});

test('settings preserve valid configured values', () => {
  assert.deepEqual(plain(normalize({ setupDone: true, gpu: 'never', audio: false, roots: [], maxResults: 40, warmMinutes: 5, imageBudget: 140, shortcut: 'SUPER + E', ignoredVolumes: [] })),
    { setupDone: true, gpu: 'never', audio: false, roots: [], maxResults: 40, warmMinutes: 5, imageBudget: 140, shortcut: 'SUPER + E', ignoredVolumes: [] });
});

test('settings clamp invalid values to defaults without coercion', () => {
  assert.deepEqual(plain(normalize({ setupDone: 'true', gpu: 'always', audio: 0 })),
    { setupDone: false, gpu: 'auto', audio: true, roots: [], maxResults: 40, warmMinutes: 5, imageBudget: 140, shortcut: 'SUPER + E', ignoredVolumes: [] });
});

test('merge preserves unknown keys including nested settings', () => {
  const entry = Object.freeze({ enabled: true, roots: [{ path: '/x', volume: 'v', excludes: [] }],
    audio: true, gpu: 'auto' });
  const changes = Object.freeze({ audio: false, setupDone: true, future: { mode: 'on' }, maxResults: 40, warmMinutes: 5, imageBudget: 140, shortcut: 'SUPER + E', ignoredVolumes: [] });
  assert.deepEqual(plain(merge(entry, changes)), { enabled: true,
    roots: [{ path: '/x', volume: 'v', excludes: [] }], audio: false, gpu: 'auto',
    setupDone: true, future: { mode: 'on' }, maxResults: 40, warmMinutes: 5, imageBudget: 140, shortcut: 'SUPER + E', ignoredVolumes: [] });
  assert.equal(entry.audio, true);
});

test('merge accepts absent entries and normalizes invalid known keys', () => {
  assert.deepEqual(plain(merge(null, { gpu: 'bad', audio: 'false' })),
    { setupDone: false, gpu: 'auto', audio: true, roots: [], maxResults: 40, warmMinutes: 5, imageBudget: 140, shortcut: 'SUPER + E', ignoredVolumes: [] });
  assert.deepEqual(plain(merge(undefined, undefined)),
    { setupDone: false, gpu: 'auto', audio: true, roots: [], maxResults: 40, warmMinutes: 5, imageBudget: 140, shortcut: 'SUPER + E', ignoredVolumes: [] });
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

test('media budgets validate without coercion', () => {
  for (const budget of [70, 140, 280]) assert.equal(normalize({imageBudget: budget}).imageBudget, budget);
  for (const budget of [71, true, '280', null]) assert.equal(normalize({imageBudget: budget}).imageBudget, 140);
});

test('a legacy codeRoots is ignored on load and dropped on the next write', () => {
  const entry = Object.freeze({ id: 'radimsem.omafind', codeRoots: [{ path: '/h/repo', excludes: [] }] });
  assert.equal(Object.hasOwn(normalize(entry), 'codeRoots'), false);
  const written = plain(merge(entry, { audio: false }));
  assert.equal(Object.hasOwn(written, 'codeRoots'), false);
  assert.equal(written.id, 'radimsem.omafind');
});

test('shortcut accepts MODS + KEY and falls back otherwise', () => {
  for (const value of ['F9', 'F35', 'SUPER + F9']) assert.equal(normalize({ shortcut: value }).shortcut, value);
  for (const value of ['F36', 'F0']) assert.equal(normalize({ shortcut: value }).shortcut, 'SUPER + E');

  assert.equal(normalize({ shortcut: 'SUPER + SHIFT + D' }).shortcut, 'SUPER + SHIFT + D');
  for (const value of ['super + e', 'SUPER', 'SUPER + SUPER + E', 'E', 7, 'SUPER + CTRL']) {
    assert.equal(normalize({ shortcut: value }).shortcut, 'SUPER + E');
  }
});

test('findEntry searches bar sections before plugins and tolerates missing layouts', () => {
  const { findEntry }=load('Settings.js');
  const plugin={id:'omafind',roots:[]};
  assert.deepEqual(plain(findEntry({plugins:[null,plugin]},'omafind')),plugin);
  for(const section of ['left','center','right']) {
    assert.deepEqual(plain(findEntry({bar:{layout:{[section]:[null,plugin]}}},'omafind')),plugin);
  }
  assert.equal(findEntry({bar:{layout:{left:[{id:'omafind',place:'bar'}]}},plugins:[plugin]},'omafind').place,'bar');
  for(const config of [null,{}, {bar:{layout:{left:'bad'}},plugins:[] }]) assert.equal(findEntry(config,'omafind'),null);
});

test('setup writes retain nested roots and unrelated settings through JSON', () => {
  const entry = {id: 'radimsem.omafind', enabled: true, future: {mode: 'keep'}};
  const changes = {setupDone: true, roots: [{path: '/home/u/Documents', volume: 'v', excludes: ['tax/2024']}]};
  const written = JSON.parse(JSON.stringify(merge(entry, changes)));
  assert.equal(written.enabled, true);
  assert.deepEqual(written.future, {mode: 'keep'});
  assert.deepEqual(written.roots, changes.roots);
  assert.equal(normalize(written).setupDone, true);
});

test('ignored volumes round trip and drop invalid entries', () => {
  assert.deepEqual(plain(normalize({ignoredVolumes: ['usb', '', null, 7, 'other']}).ignoredVolumes), ['usb', 'other']);
  for (const ignoredVolumes of [null, 'usb', 7]) {
    assert.deepEqual(plain(normalize({ignoredVolumes}).ignoredVolumes), []);
  }
  const written = JSON.parse(JSON.stringify(merge({future: true}, {ignoredVolumes: ['usb']})));
  assert.deepEqual(plain(normalize(written).ignoredVolumes), ['usb']);
  assert.equal(written.future, true);
});
