import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';

test('failed attempts increase the delay linearly up to two seconds', () => {
  const { delay } = load('Backoff.js');
  assert.deepEqual(Array.from({ length: 12 }, (_, i) => delay(i + 1)),
    [200, 400, 600, 800, 1000, 1200, 1400, 1600, 1800, 2000, 2000, 2000]);
});
