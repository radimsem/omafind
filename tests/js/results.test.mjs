import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
import { fixture, freeze, plain } from './fixtures.mjs';

test('group sections follow best hit order and retain flat order within each kind', () => {
  const { group, sectionTitle } = load('format.js', 'results.js');
  const items = fixture('main').items;
  const view = group(items, { expanded: false });
  assert.deepEqual(plain(view.sections.map(section => section.kind)), ['image', 'pdf', 'text']);
  assert.deepEqual(plain(view.rows.filter(row => row.type === 'header')), [
    { type: 'header', key: 'h:image', kind: 'image', title: 'Images', count: 5 },
    { type: 'header', key: 'h:pdf', kind: 'pdf', title: 'PDFs', count: 2 },
    { type: 'header', key: 'h:text', kind: 'text', title: 'Documents', count: 7 }
  ]);
  assert.deepEqual(plain(view.rows.filter(row => row.kind === 'image' || row.item?.kind === 'image')
    .filter(row => row.type === 'item').map(row => row.key)), ['image:1', 'image:2', 'image:3', 'image:4', 'image:5']);
  assert.deepEqual(plain(view.rows[1]), { type: 'item', key: 'image:1', item: items[0], badge: '', weak: false });
  const reordered = group([items[4], items[6], items[0]], { expanded: false });
  assert.deepEqual(plain(reordered.sections.map(section => section.kind)), ['pdf', 'text', 'image']);
  for (const [kind, title] of [['image', 'Images'], ['video', 'Video'], ['audio', 'Audio'],
    ['pdf', 'PDFs'], ['text', 'Documents'], ['code', 'Code']]) assert.equal(sectionTitle(kind), title);
});

test('weak results fold once at the end or expand without section headers', () => {
  const { group } = load('format.js', 'results.js');
  const items = fixture('main').items;
  const folded = group(items, { expanded: false });
  assert.equal(folded.weakCount, 3);
  assert.deepEqual(plain(folded.rows.at(-1)), { type: 'weak', key: 'weak', count: 3, expanded: false });
  assert.equal(folded.rows.filter(row => row.type === 'item').length, 14);
  const expanded = group(items, { expanded: true });
  assert.equal(expanded.weakCount, 3);
  assert.deepEqual(plain(expanded.rows.at(-4)), { type: 'weak', key: 'weak', count: 3, expanded: true });
  assert.deepEqual(plain(expanded.rows.slice(-3).map(row => [row.key, row.weak])),
    [['image:6', true], ['pdf:3', true], ['text:8', true]]);
  assert.deepEqual(plain(group([], { expanded: false })), { rows: [], sections: [], weakCount: 0 });
  const onlyWeak = group(items.slice(-3), { expanded: true });
  assert.equal(onlyWeak.sections.length, 0);
  assert.equal(onlyWeak.rows.length, 4);
});

test('badge comes from offline field before location for each kind', () => {
  const { badge, group } = load('format.js', 'results.js');
  assert.equal(badge(fixture('offline').items[0]), 'offline');
  for (const [kind, want] of [['image', ''], ['video', '14:32'], ['audio', '7:55'],
    ['pdf', 'p. 12'], ['text', 'L41'], ['code', 'L8']]) {
    const item = fixture(kind).items[0];
    assert.equal(badge(item), want);
    assert.equal(group([item], { expanded: false }).rows[1].badge, want);
  }
});

test('selection starts on the top hit, crosses headers, and never wraps', () => {
  const { group, selectable, firstSelection, move } = load('format.js', 'results.js');
  const rows = group([fixture('image').items[0], fixture('pdf').items[0],
    { ...fixture('text').items[0], weak: true }], { expanded: false }).rows;
  assert.deepEqual(plain(selectable(rows)), [1, 3, 4]);
  assert.equal(firstSelection(rows), 1);
  assert.equal(move(rows, 1, 1), 3);
  assert.equal(move(rows, 3, -1), 1);
  assert.equal(move(rows, 1, -1), 1);
  assert.equal(move(rows, 4, 1), 4);
  assert.equal(move(rows, -1, 1), 1);
  assert.equal(firstSelection([]), -1);
  assert.equal(move([], -1, 1), -1);
  assert.equal(firstSelection([{ type: 'header' }]), -1);
});

test('selection follows its key on regroup and resets to top on a new result set', () => {
  const { group, firstSelection, selectionAfterRegroup } = load('format.js', 'results.js');
  const image = fixture('image').items[0];
  const pdf = fixture('pdf').items[0];
  const oldRows = group([image, pdf], { expanded: false }).rows;
  const newRows = group([pdf, image], { expanded: false }).rows;
  assert.equal(selectionAfterRegroup(oldRows, 1, newRows), 3);
  assert.equal(firstSelection(newRows), 1);
  assert.equal(selectionAfterRegroup(oldRows, 1, group([pdf], {}).rows), 1);
  assert.equal(selectionAfterRegroup(oldRows, -1, newRows), 1);
  assert.equal(selectionAfterRegroup(oldRows, 1, []), -1);
});

test('meaning replies win in either arrival order, stale sequences drop, and current errors display', () => {
  const { merge } = load('format.js', 'results.js');
  const meaning = fixture('main');
  const words = freeze({ ...meaning, legs: ['words'] });
  assert.equal(merge(null, words, 7), words);
  assert.equal(merge(words, meaning, 7), meaning);
  assert.equal(merge(meaning, words, 7), meaning);
  assert.equal(merge(meaning, { ...meaning, seq: 6 }, 7), meaning);
  assert.equal(merge(words, { ...meaning, seq: 8 }, 7), words);
  assert.equal(merge({ ...meaning, seq: 6 }, words, 7), words);
  const error = freeze({ t: 'error', seq: 7, reason: 'No index exists.' });
  assert.equal(merge(meaning, error, 7), error);
  assert.equal(merge(meaning, { ...error, seq: 6 }, 7), meaning);
});

test('footer copy uses daemon totals, weaker counts, phases, and code prefix', () => {
  const { footerLeft } = load('format.js', 'results.js');
  assert.equal(footerLeft({ reply: fixture('main'), phase: 'done' }), '17 results · 3 weaker');
  assert.equal(footerLeft({ reply: fixture('main'), phase: 'words' }), 'Matching words…');
  assert.equal(footerLeft({ reply: fixture('degraded'), phase: 'degraded', prefix: 'code' }),
    '6 results · keyword matches only');
  assert.equal(footerLeft({ reply: { total: 4, weaker: 5 }, prefix: 'code' }), '4 results in your code · 5 weaker');
  assert.equal(footerLeft({ reply: { total: 4, weaker: 5 }, prefix: 'code:' }), '4 results in your code · 5 weaker');
  assert.equal(footerLeft({ reply: { total: 1, weaker: 0 } }), '1 result');
  assert.equal(footerLeft({ reply: { total: 1204, weaker: 0 } }), '1,204 results');
  assert.equal(footerLeft({ reply: { total: 2, weaker: 0, degraded: { code: 'server-starting',
    title: 'The embedding server is starting.', detail: 'Showing keyword matches until it is ready.' } },
  phase: 'degraded' }), '2 results · keyword matches only');
});

test('idle footer uses offline labels and only shows incomplete indexing progress', () => {
  const { footerIdle } = load('format.js', 'results.js');
  const status = freeze({ files: 3880, roots: 4, offline: ['Photos2024'], done: 1204, total: 1209 });
  const footer = footerIdle(status);
  assert.equal(footer.text, '3,880 files · watching 4 folders · Photos2024 offline');
  assert.equal(footer.progress.text, 'Indexing 1,204 of 1,209');
  assert.equal(footer.progress.fraction, 1204 / 1209);
  assert.deepEqual(plain(footerIdle({ files: 1, roots: 1, offline: ['Photos', 'Backup'], done: 1, total: 1 })),
    { text: '1 files · watching 1 folder · Photos offline · Backup offline', progress: null });
  assert.equal(footerIdle({ files: 0, roots: 0, offline: [], done: 0, total: 0 }).progress, null);
});

test('jump moves by selectable rows and clamps at both ends', () => {
  const { group, jump, selectable } = load('format.js', 'results.js');
  const rows = group(fixture('main').items, { expanded: false }).rows;
  const indexes = selectable(rows);
  assert.equal(jump(rows, indexes[0], 3), indexes[3]);
  assert.equal(jump(rows, indexes[5], -2), indexes[3]);
  assert.equal(jump(rows, indexes[2], 1000), indexes.at(-1));
  assert.equal(jump(rows, indexes[2], -1000), indexes[0]);
  assert.equal(jump(rows, indexes[2], Infinity), indexes.at(-1));
  assert.equal(jump(rows, indexes[2], -Infinity), indexes[0]);
  assert.equal(jump(rows, -1, 1), indexes[0]);
  assert.equal(jump([], 0, 1), -1);
});

test('a code search with no code index explains the empty result', () => {
  const R = load('format.js', 'results.js');
  assert.equal(R.footerLeft({ phase: 'done', prefix: 'code:',
    reply: { total: 0, items: [], notice: 'no-code-index' } }),
    'No code is indexed yet. Turn on Code for a repository in setup.');
});

test('a code search before the first code index says the index is pending', () => {
  const R = load('format.js', 'results.js');
  assert.equal(R.footerLeft({ phase: 'done', prefix: 'code:',
    reply: { total: 0, items: [], notice: 'code-index-pending' } }),
    'The code index is not built yet. It is built on the next index run.');
});

test('the banner slot shows one error and names what its Retry does', () => {
  const R = load('format.js', 'errors.js', 'results.js');
  const update = { code: 'update-failed', title: 'omafindd did not update.',
    detail: 'uv sync failed. Press Retry to try again.', fix: { kind: 'retry' } };
  const offline = R.offline('');
  const degraded = fixture('degraded');
  const warm = { code: 'server-start-failed', title: 'The embedding server did not start.',
    detail: 'It exited with code 1. Showing keyword matches until it starts.', fix: { kind: 'retry' } };
  assert.equal(R.bannerFor({ reply: fixture('main') }), null);
  assert.deepEqual(plain(R.bannerFor({ update, offline, reply: degraded })), { error: update, retry: 'update' });
  assert.equal(R.bannerFor({ offline, reply: degraded }).retry, 'connect');
  assert.deepEqual(plain(R.bannerFor({ reply: degraded, warm })), { error: plain(degraded.degraded), retry: 'warm' });
  assert.deepEqual(plain(R.bannerFor({ reply: fixture('main'), warm })), { error: warm, retry: 'warm' });
  assert.deepEqual(plain(R.bannerFor({ reply: { t: 'error', seq: 4, code: 'no-index',
    title: 'Nothing is indexed yet.', detail: 'Open setup and start the first index.' } })),
  { error: { code: 'no-index', title: 'Nothing is indexed yet.', detail: 'Open setup and start the first index.' },
    retry: 'search' });
  assert.deepEqual(plain(R.bannerFor({ reply: { ...fixture('main'), degraded: 'Vulkan device lost' } })),
    { error: { code: 'unknown', title: 'Vulkan device lost', detail: '' }, retry: 'search' });
});

test('a code search while the code index is being built says so', () => {
  const R = load('format.js', 'results.js');
  assert.equal(R.footerLeft({ phase: 'done', prefix: 'code:',
    reply: { total: 3, weaker: 0, items: [], notice: 'code-index-building' } }),
    '3 results in your code · the code index is still being built');
});
