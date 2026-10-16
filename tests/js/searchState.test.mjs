import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
import { fixture, freeze, plain } from './fixtures.mjs';

const search = () => load('format.js', 'results.js', 'searchState.js');

test('prefixes are lowercase, anchored, and strip only leading spaces from the remaining query', () => {
  const { parse } = search();
  for (const [prefix, kind] of [['img:', 'image'], ['pdf:', 'pdf'], ['doc:', 'text'],
    ['vid:', 'video'], ['aud:', 'audio']]) {
    assert.deepEqual(plain(parse(prefix + '  router ')), { prefix, kind, text: 'router ' });
  }
  for (const query of ['IMG: router', ' img: router', 'find img: router', 'router', 'code: router']) {
    assert.deepEqual(plain(parse(query)), { prefix: null, kind: null, text: query });
  }
});

test('typing starts a new sequence and keeps send outside stored state', () => {
  const { initial, reduce } = search();
  const state = freeze(initial());
  assert.deepEqual(plain(state), { query: '', seq: 0, phase: 'idle', sentWords: 0,
    sentMeaning: 0, reply: null, started: 0 });
  const typed = reduce(state, freeze({ type: 'typed', query: 'router', now: 1000 }));
  assert.deepEqual(plain(typed), { state: { query: 'router', seq: 1, phase: 'words',
    sentWords: 0, sentMeaning: 0, reply: null, started: 1000 }, send: null });
  const next = reduce(freeze(typed.state), { type: 'typed', query: 'router talk', now: 1020 });
  assert.equal(next.state.seq, 2);
  assert.equal(next.state.started, 1020);
  assert.equal(Object.hasOwn(next.state, 'send'), false);
});

test('words and meaning send once per sequence at their debounce deadlines', () => {
  const { initial, reduce, wordsDelay, meaningDelay } = search();
  const typed = reduce(initial(), { type: 'typed', query: 'pdf:  where they tal', now: 1000 }).state;
  assert.equal(reduce(freeze(typed), { type: 'words-due', now: 1000 + wordsDelay - 1 }).send, null);
  const words = reduce(freeze(typed), { type: 'words-due', now: 1050 });
  assert.deepEqual(plain(words.send),
    { t: 'search', seq: 1, q: 'where they tal', legs: ['words'], kinds: ['pdf'] });
  assert.equal(words.state.sentWords, 1);
  assert.equal(reduce(freeze(words.state), { type: 'words-due', now: 1100 }).send, null);
  assert.equal(reduce(freeze(words.state), { type: 'meaning-due', now: 1000 + meaningDelay - 1 }).send, null);
  const meaning = reduce(freeze(words.state), { type: 'meaning-due', now: 1200 });
  assert.deepEqual(plain(meaning.send),
    { t: 'search', seq: 1, q: 'where they tal', legs: ['words', 'meaning'], kinds: ['pdf'] });
  assert.equal(meaning.state.sentMeaning, 1);
  assert.equal(reduce(freeze(meaning.state), { type: 'meaning-due', now: 1300 }).send, null);
  assert.equal(Object.hasOwn(meaning.state, 'send'), false);
  const newQuery = reduce(freeze(meaning.state), { type: 'typed', query: 'talk', now: 1400 }).state;
  assert.deepEqual(plain(reduce(freeze(newQuery), { type: 'words-due', now: 1450 }).send),
    { t: 'search', seq: 2, q: 'talk', legs: ['words'] });
});

test('late words timers cannot send after meaning already requested both legs', () => {
  const { initial, reduce } = search();
  const typed = reduce(initial(), { type: 'typed', query: 'router', now: 100 }).state;
  const meaning = reduce(freeze(typed), { type: 'meaning-due', now: 300 });
  assert.deepEqual(plain(meaning.send.legs), ['words', 'meaning']);
  assert.equal(reduce(freeze(meaning.state), { type: 'words-due', now: 350 }).send, null);
});

test('clearing idles without incrementing seq and ignores queued replies and timers', () => {
  const { initial, reduce, status } = search();
  const typed = reduce(initial(), { type: 'typed', query: 'router', now: 100 }).state;
  for (const query of ['', '   ']) {
    const cleared = reduce(freeze(typed), { type: 'typed', query, now: 200 });
    assert.equal(cleared.state.seq, 1);
    assert.equal(cleared.state.phase, 'idle');
    assert.equal(cleared.state.reply, null);
    assert.deepEqual(plain(status(cleared.state)), { text: 'ready', spinner: false });
    assert.equal(reduce(freeze(cleared.state), { type: 'words-due', now: 250 }).send, null);
    assert.equal(reduce(freeze(cleared.state), { type: 'meaning-due', now: 400 }).send, null);
    assert.equal(reduce(freeze(cleared.state), { type: 'reply', reply: { ...fixture('main'), seq: 1 } }).state.reply, null);
  }
  const prefixOnly = reduce(initial(), { type: 'typed', query: 'img:', now: 100 }).state;
  assert.equal(reduce(prefixOnly, { type: 'meaning-due', now: 300 }).send, null);
});

test('accepted replies update phase and timing, while stale or lower-priority replies leave them unchanged', () => {
  const { initial, reduce, status } = search();
  const typed = reduce(initial(), { type: 'typed', query: 'router', now: 100 }).state;
  const meaning = freeze({ ...fixture('main'), seq: 1 });
  const words = freeze({ ...meaning, legs: ['words'] });
  const interim = reduce(freeze(typed), { type: 'reply', reply: words });
  assert.equal(interim.state.phase, 'words');
  assert.deepEqual(plain(status(interim.state, words)), { text: 'matching by meaning', spinner: true });
  const done = reduce(freeze(interim.state), { type: 'reply', reply: meaning });
  assert.equal(done.state.phase, 'done');
  assert.deepEqual(plain(status(done.state, meaning)), { text: '38 ms', spinner: false });
  const lateWords = reduce(freeze(done.state), { type: 'reply', reply: words });
  assert.equal(lateWords.state.phase, 'done');
  assert.equal(lateWords.state.reply, meaning);
  const stale = reduce(freeze(interim.state), { type: 'reply', reply: fixture('main') });
  assert.equal(stale.state.phase, 'words');
  assert.equal(stale.state.reply, words);
  const reversed = reduce(freeze(typed), { type: 'reply', reply: meaning });
  assert.equal(reduce(freeze(reversed.state), { type: 'reply', reply: words }).state.reply, meaning);
  const degraded = reduce(freeze(typed), { type: 'reply', reply: { ...fixture('degraded'), seq: 1 } });
  assert.equal(degraded.state.phase, 'degraded');
  assert.deepEqual(plain(status(degraded.state, degraded.state.reply)), { text: '38 ms', spinner: false });
  const error = freeze({ t: 'error', seq: 1, reason: 'No index exists.' });
  assert.equal(reduce(freeze(done.state), { type: 'reply', reply: error }).state.reply, error);
});

test('prefixed replies filter items locally without altering daemon replies or their counts', () => {
  const { initial, reduce } = search();
  const typed = reduce(initial(), { type: 'typed', query: 'pdf: router', now: 100 }).state;
  const reply = freeze({ ...fixture('main'), seq: 1 });
  const filtered = reduce(freeze(typed), { type: 'reply', reply }).state.reply;
  assert.deepEqual(plain(filtered.items.map(item => item.kind)), ['pdf', 'pdf', 'pdf']);
  assert.equal(filtered.total, 17);
  assert.equal(filtered.weaker, 3);
  assert.equal(reply.items.length, 17);
  const words = freeze({ ...reply, legs: ['words'] });
  assert.equal(reduce(freeze({ ...typed, reply: filtered, phase: 'done' }),
    { type: 'reply', reply: words }).state.reply, filtered);
});

test('highlighting matches whole words case-insensitively and only the typed part of the last word', () => {
  const { lastWordPrefix, highlight } = search();
  assert.equal(lastWordPrefix('where they tal'), 'tal');
  assert.equal(lastWordPrefix('pdf: where they tal'), 'tal');
  assert.equal(lastWordPrefix('where they '), '');
  assert.equal(lastWordPrefix(''), '');
  assert.equal(lastWordPrefix('img:'), '');
  assert.deepEqual(plain(highlight('WHERE they talk, otherwhere.', freeze(['where', 'they']), 'tal')), [
    { t: 'WHERE', m: true }, { t: ' ', m: false }, { t: 'they', m: true },
    { t: ' ', m: false }, { t: 'tal', m: true }, { t: 'k, otherwhere.', m: false }
  ]);
  assert.deepEqual(plain(highlight('restart start started', ['start'], '')), [
    { t: 'restart ', m: false }, { t: 'start', m: true }, { t: ' started', m: false }
  ]);
  assert.deepEqual(plain(highlight('Talk retalk TAL', [], 'tal')), [
    { t: 'Tal', m: true }, { t: 'k retalk ', m: false }, { t: 'TAL', m: true }
  ]);
  assert.deepEqual(plain(highlight('ŽLUTÝ žlutý nežlutý', ['žlutý'], '')), [
    { t: 'ŽLUTÝ', m: true }, { t: ' ', m: false }, { t: 'žlutý', m: true }, { t: ' nežlutý', m: false }
  ]);
  assert.deepEqual(plain(highlight('anything', [], '')), [{ t: 'anything', m: false }]);
  assert.deepEqual(plain(highlight('', [], '')), []);
});

test('whole words respect punctuation boundaries in prose and code', () => {
  const { highlight, lastWordPrefix } = search();
  assert.deepEqual(plain(highlight('talk… `talk` @talk—retalk', ['talk'], '')), [
    { t: 'talk', m: true }, { t: '… `', m: false }, { t: 'talk', m: true },
    { t: '` @', m: false }, { t: 'talk', m: true }, { t: '—retalk', m: false }
  ]);
  assert.equal(lastWordPrefix('where they—tal'), 'tal');
  assert.equal(lastWordPrefix('talk…'), '');
  assert.deepEqual(plain(highlight('猫、猫咪', ['猫'], '')), [
    { t: '猫', m: true }, { t: '、猫咪', m: false }
  ]);
});


test('prefix-only clears old results and ignores replies for the cleared kind', () => {
  const { initial, reduce } = search();
  const old = { ...initial(), query: 'router', seq: 1, phase: 'done', reply: { ...fixture('main'), seq: 1 } };
  const idle = reduce(old, { type: 'typed', query: 'img:  ', now: 100 }).state;
  assert.equal(idle.phase, 'idle');
  assert.equal(idle.reply, null);
  assert.equal(reduce(idle, { type: 'reply', reply: { ...fixture('main'), seq: idle.seq } }).state.reply, null);
  assert.equal(reduce(idle, { type: 'words-due', now: 500 }).send, null);
});

test('new sequence exposes words phase to footer while old results remain visible', () => {
  const { initial, reduce, footerLeft, status } = search();
  const old = { ...initial(), query: 'router', seq: 1, phase: 'done', reply: { ...fixture('main'), seq: 1 } };
  const typing = reduce(old, { type: 'typed', query: 'talk', now: 100 }).state;
  assert.equal(footerLeft(typing), 'Matching words…');
  assert.equal(status(typing).text, '');
});

test('latency shows whole milliseconds', () => {
  const { initial, reduce, status } = search();
  const typed = reduce(initial(), { type: 'typed', query: 'router', now: 100 }).state;
  const reply = freeze({ ...fixture('main'), seq: 1, ms: { total: 17.418 } });
  const done = reduce(freeze(typed), { type: 'reply', reply });
  assert.deepEqual(plain(status(done.state, reply)), { text: '17 ms', spinner: false });
});


test('an early meaning tick reports the time left and a later tick sends once', () => {
  const { initial, reduce, remaining } = search();
  let state = reduce(initial(), { type: 'typed', query: 'router', now: 1000 }).state;
  state = reduce(state, { type: 'words-due', now: 1050 }).state;
  const early = reduce(state, { type: 'meaning-due', now: 1199 });
  assert.equal(early.send, null);
  assert.equal(remaining(state, 'meaning-due', 1199), 1);
  const late = reduce(early.state, { type: 'meaning-due', now: 1200 });
  assert.deepEqual(plain(late.send.legs), ['words', 'meaning']);
  assert.equal(remaining(late.state, 'meaning-due', 1300), 0);
  assert.equal(reduce(late.state, { type: 'meaning-due', now: 1300 }).send, null);
});
