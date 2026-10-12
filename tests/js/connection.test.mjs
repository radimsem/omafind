import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';

const { initial, reduce } = load('Connection.js');
const plain = value => JSON.parse(JSON.stringify(value));

test('initial connection has unknown unit state and no failures', () => {
  assert.deepEqual(plain(initial()), { unit: 'unknown', socket: 'closed', failures: 0 });
});

test('unit checks record enabled and missing states', () => {
  assert.equal(reduce(initial(), { type: 'unit', enabled: true }).unit, 'enabled');
  assert.equal(reduce(initial(), { type: 'unit', enabled: false }).unit, 'missing');
});

test('opening the socket waits for state before readiness', () => {
  let state = reduce(initial(), { type: 'attempt-failed' });
  state = reduce(state, { type: 'socket-open' });
  assert.equal(state.socket, 'open');
  assert.equal(state.failures, 1);
  state = reduce(state, { type: 'state' });
  assert.equal(state.socket, 'ready');
  assert.equal(state.failures, 0);
});

test('failed attempts close the socket and accumulate failures', () => {
  let state = reduce(initial(), { type: 'state' });
  for (let i = 0; i < 4; i++) state = reduce(state, { type: 'attempt-failed' });
  assert.equal(state.socket, 'closed');
  assert.equal(state.failures, 4);
  assert.equal(reduce(state, { type: 'state' }).failures, 0);
});

test('a failure after readiness starts a new retry sequence', () => {
  const state = reduce(reduce(initial(), { type: 'state' }), { type: 'attempt-failed' });
  assert.equal(state.socket, 'closed');
  assert.equal(state.failures, 1);
});

test('reducing an event leaves the previous connection unchanged', () => {
  for (const event of [{ type: 'unit', enabled: true }, { type: 'socket-open' },
    { type: 'state' }, { type: 'attempt-failed' }, { type: 'unknown' }]) {
    const state = Object.freeze({ unit: 'enabled', socket: 'ready', failures: 4 });
    assert.notEqual(reduce(state, event), state);
    assert.deepEqual(state, { unit: 'enabled', socket: 'ready', failures: 4 });
  }
});
