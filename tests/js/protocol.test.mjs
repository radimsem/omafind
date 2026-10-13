import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';

test('hello encodes as one versioned JSON line', () => {
  const { encode, hello } = load('Protocol.js');
  assert.equal(encode(hello()), '{"t":"hello","v":1}\n');
});

test('encoding escapes embedded newlines', () => {
  assert.equal(load('Protocol.js').encode({ t: 'hello', v: 1, text: 'a\nb' }),
    '{"t":"hello","v":1,"text":"a\\nb"}\n');
});

for (const line of ['', '   ', 'nope', '[1]', 'null', '1', 'true', '"text"',
  '{}', '{"t":"state","v":2}', '{"t":"state","v":"1"}']) {
  test(`decode rejects invalid rows and other versions: ${JSON.stringify(line)}`, () => {
    assert.equal(load('Protocol.js').decode(line), null);
  });
}

test('decode accepts a versioned state row', () => {
  const reply = load('Protocol.js').decode(
    '{"t":"state","v":1,"runtime":"ready","model":"missing","embedder":"text"}\n');
  assert.deepEqual(JSON.parse(JSON.stringify(reply)),
    { t: 'state', v: 1, runtime: 'ready', model: 'missing', embedder: 'text' });
});

test('decode accepts an unversioned results row', () => {
  const reply = load('Protocol.js').decode('{"t":"results","seq":3,"items":[]}');
  assert.deepEqual(JSON.parse(JSON.stringify(reply)), { t: 'results', seq: 3, items: [] });
});
