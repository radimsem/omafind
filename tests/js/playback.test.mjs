import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
import { fixture, freeze, plain } from './fixtures.mjs';

test('playback starts at the hit and toggles pause/resume without resetting position', () => {
  const { initial, reduce } = load('playback.js');
  assert.deepEqual(plain(initial()), { id: null, playing: false, position: 0, start: 0 });
  const item = fixture('audio').items[0];
  const started = reduce(freeze(initial()), freeze({ type: 'toggle', item }));
  assert.deepEqual(plain(started), {
    state: { id: 'audio:1', playing: true, position: 475, start: 475 },
    command: { op: 'start', path: item.path, start: 475 }
  });
  const position = reduce(freeze(started.state), { type: 'position', seconds: 480 });
  assert.equal(position.command, null);
  const paused = reduce(freeze(position.state), { type: 'toggle', item });
  assert.equal(paused.state.playing, false);
  assert.deepEqual(plain(paused.command), { op: 'pause' });
  const resumed = reduce(freeze(paused.state), { type: 'toggle', item });
  assert.deepEqual(plain(resumed.state), { id: 'audio:1', playing: true, position: 480, start: 475 });
  assert.deepEqual(plain(resumed.command), { op: 'resume' });
});

test('selection changes stop playing or paused previews, same selection has no command', () => {
  const { initial, reduce } = load('playback.js');
  const item = fixture('audio').items[0];
  const started = reduce(initial(), { type: 'toggle', item }).state;
  const same = reduce(freeze(started), { type: 'selection', id: item.id });
  assert.notEqual(same.state, started);
  assert.deepEqual(plain(same.state), plain(started));
  assert.equal(same.command, null);
  for (const playing of [true, false]) {
    assert.deepEqual(plain(reduce(freeze({ ...started, playing }), { type: 'selection', id: null })),
      { state: { id: null, playing: false, position: 0, start: 0 }, command: { op: 'stop' } });
  }
  assert.equal(reduce(initial(), { type: 'selection', id: 'video:1' }).command, null);
});

test('another item restarts at its match and ending clears playback for a fresh toggle', () => {
  const { initial, reduce, mpvArgs } = load('playback.js');
  const audio = fixture('audio').items[0];
  const video = fixture('video').items[0];
  const playing = reduce(initial(), { type: 'toggle', item: audio }).state;
  const switched = reduce(freeze(playing), { type: 'toggle', item: video });
  assert.deepEqual(plain(switched.command), { op: 'start', path: video.path, start: 872 });
  assert.deepEqual(plain(reduce(freeze(switched.state), { type: 'ended' })),
    { state: { id: null, playing: false, position: 0, start: 0 }, command: null });
  assert.equal(reduce(initial(), { type: 'toggle', item: { ...audio, loc: null } }).state.start, 0);
  assert.deepEqual(plain(mpvArgs('/home/u/a b.mp3', 475, '/run/user/1000/omafind/mpv.sock')),
    ['mpv', '--no-video', '--no-terminal', '--start=475',
      '--input-ipc-server=/run/user/1000/omafind/mpv.sock', '--', '/home/u/a b.mp3']);
});
