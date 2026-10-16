import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';

const installer = () => load('installer.js');

function run(events, state) {
  const I = installer();
  let next = state || I.initial();
  for (const event of events) next = I.reduce(next, event);
  return next;
}

test('the overlay stands aside from launch until the install terminal closes', () => {
  assert.equal(run([{type: 'launch', terminals: 1}]).aside, true);
  assert.equal(run([{type: 'launch', terminals: 1}, {type: 'terminals', terminals: 2}]).aside, true);
  assert.equal(run([{type: 'launch', terminals: 1}, {type: 'terminals', terminals: 2},
    {type: 'terminals', terminals: 1}]).aside, false);
});

test('a terminal that never opens brings the overlay back after the launch timeout', () => {
  assert.equal(run([{type: 'launch', terminals: 0}, {type: 'timeout'}]).aside, false);
  assert.equal(run([{type: 'launch', terminals: 0}, {type: 'terminals', terminals: 1},
    {type: 'timeout'}]).aside, true);
});

test('another terminal closing before the install terminal opens keeps the overlay aside', () => {
  assert.equal(run([{type: 'launch', terminals: 2}, {type: 'terminals', terminals: 1}]).aside, true);
});

test('opening omafind ends standing aside, and later changes are ignored', () => {
  const ended = run([{type: 'launch', terminals: 0}, {type: 'terminals', terminals: 1}, {type: 'end'}]);
  assert.equal(ended.aside, false);
  assert.equal(run([{type: 'terminals', terminals: 3}], ended).aside, false);
});
