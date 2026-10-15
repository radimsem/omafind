import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
import { fixture, freeze, plain } from './fixtures.mjs';

test('durations floor seconds and show hours only from one hour', () => {
  const { duration, windowCaption } = load('format.js');
  for (const [seconds, want] of [[7.9, '0:07'], [475, '7:55'], [2900, '48:20'],
    [3599, '59:59'], [3600, '1:00:00'], [5525, '1:32:05'], [0, '0:00']]) {
    assert.equal(duration(seconds), want);
  }
  assert.equal(windowCaption(475, 505, 823), '7:55 – 8:25 of 13:43');
});

test('counts and decimal sizes use the specified precision', () => {
  const { count, size } = load('format.js');
  assert.equal(count(3880), '3,880');
  assert.equal(count(1204009), '1,204,009');
  assert.equal(count(0), '0');
  for (const [bytes, want] of [[640, '640 B'], [48000, '48 KB'], [1200000000, '1.2 GB'],
    [1000, '1.0 KB'], [9999, '10.0 KB'], [10000, '10 KB'], [0, '0 B'],
    [4500000, '4.5 MB'], [1200000000000, '1.2 TB']]) {
    assert.equal(size(bytes), want);
  }
});

test('local dates and metadata skip absent facts while retaining zero', () => {
  const { date, meta, kindLabel } = load('format.js');
  const noon = new Date(2025, 5, 12, 12).getTime() / 1000;
  assert.equal(date(noon), 'Jun 12, 2025');
  assert.equal(meta({ kind: 'video', mtime: noon, info: { duration: 2900 }, size: 1200000000 }),
    'Video · Jun 12, 2025 · 48:20 · 1.2 GB');
  assert.equal(meta({ kind: 'pdf', info: { pages: 412 } }), 'PDF · 412 pages');
  assert.equal(meta({ kind: 'audio', info: { duration: 0 }, size: 0 }), 'Audio · 0:00 · 0 B');
  assert.equal(meta({ kind: 'image' }), 'Image');
  assert.equal(meta({ kind: 'text', info: { extracted: true, pages: 2, duration: 10 } }), 'Text');
  for (const [kind, label] of [['image', 'Image'], ['video', 'Video'], ['audio', 'Audio'],
    ['pdf', 'PDF'], ['text', 'Text'], ['code', 'Code']]) assert.equal(kindLabel(kind), label);
});

test('jump values use seconds, pages, line ranges, and code open_line', () => {
  const { at } = load('format.js');
  for (const [item, want] of [[{ kind: 'image', loc: 12 }, null],
    [{ kind: 'video', loc: 872 }, '14:32'], [{ kind: 'audio', loc: 0 }, '0:00'],
    [{ kind: 'pdf', loc: 12 }, 'p. 12'], [{ kind: 'text', loc: 41 }, 'L41'],
    [{ kind: 'text', loc: 1, loc_end: 47 }, 'L1–47'],
    [{ kind: 'text', loc: 1, loc_end: 47, open_line: 8 }, 'L1–47'],
    [{ kind: 'code', loc: 1, loc_end: 47, open_line: 8 }, 'L8'],
    [{ kind: 'code', loc: 1, loc_end: 47 }, 'L1–47'],
    [{ kind: 'text', loc: 41, loc_end: 20 }, 'L41'], [{ kind: 'pdf', loc: null }, null]]) {
    assert.equal(at(freeze(item)), want);
  }
});

test('why tokens keep key order, accent targets and hits, and omit empty values', () => {
  const { why } = load('format.js');
  const item = fixture('pdf').items[0];
  assert.deepEqual(plain(why(item, freeze({ opener: 'omarchy-launch-browser' }))), [
    { k: 'leg', v: 'meaning + words', tone: 'plain' },
    { k: 'part', v: 'text', tone: 'plain' },
    { k: 'at', v: 'p. 12', tone: 'accent' },
    { k: 'hits', v: 'they, talk', tone: 'accent' },
    { k: 'z', v: '3.4', tone: 'plain' },
    { k: 'opener', v: 'omarchy-launch-browser', tone: 'plain' }
  ]);
  assert.deepEqual(plain(why({ kind: 'image', z: 0, hits: [] }, { opener: 'xdg-open' })),
    [{ k: 'z', v: '0.0', tone: 'plain' }]);
  assert.deepEqual(plain(why({ kind: 'audio' }, { opener: 'mpv' })), []);
  for (const kind of ['video', 'pdf', 'text', 'code']) {
    assert.deepEqual(plain(why({ kind }, { opener: 'app' })),
      [{ k: 'opener', v: 'app', tone: 'plain' }]);
  }
  assert.deepEqual(plain(why({ kind: 'text', leg: '', part: null, hits: [] }, { opener: '' })), []);
});

test('snippet normalization merges only adjacent equal match runs without mutating input', () => {
  const { snippetRuns } = load('format.js');
  const input = freeze([{ t: 'a', m: false }, { t: ' b', m: false },
    { t: 'hit', m: true }, { t: 's', m: true }, { t: '.', m: false }]);
  const runs = snippetRuns(input);
  assert.deepEqual(plain(runs), [{ t: 'a b', m: false }, { t: 'hits', m: true }, { t: '.', m: false }]);
  assert.notEqual(runs[0], input[0]);
  assert.deepEqual(plain(snippetRuns(null)), []);
});

test('qtImage accepts formats Qt decodes and rejects the rest', () => {
  const F = load('format.js');
  assert.deepEqual(['a.JPG', 'b.png', 'c.webp', 'd.heic', 'e.tiff', 'f'].map(F.qtImage),
    [true, true, true, false, false, false]);
});
