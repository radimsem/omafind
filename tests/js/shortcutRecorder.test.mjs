import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { load } from './load.mjs';

const META = 0x10000000;
function recorder() {
  const commands = [], recorded = [];
  const ctx = vm.createContext({
    Keycombo: load('keycombo.js'), recording: false, conflict: '', exposed: false,
    lost: false, nonce: '', operation: '', pendingLeave: false, leaveRetries: 0, accepted: '', polledNonce: '',
    binds: {}, transition: { running: false, exec(argv) { this.running = true; commands.push(argv); } },
    submapQuery: { running: false }, limit: { restarts: 0, stops: 0, restart() { this.restarts++; }, stop() { this.stops++; } },
    recorded(chord) { recorded.push(chord); },
  });
  Object.defineProperty(ctx, 'active', { get() { return ctx.recording; } });
  const source = readFileSync(new URL('../../ui/ShortcutRecorder.qml', import.meta.url), 'utf8');
  for (const match of source.matchAll(/^  function \w+\([^]*?^  \}/gm)) vm.runInContext(match[0], ctx);
  ctx.recorder = ctx;
  const timers = [...source.matchAll(/  Timer \{([^]*?)^  \}/gm)].map(match => match[1]);
  const poll = timers.find(timer => timer.includes('repeat: true'));
  const idle = timers.find(timer => timer.includes('id: limit'));
  const pollRunning = () => vm.runInContext(poll.match(/running: ([^\n]*)/)[1], ctx);
  const expire = () => vm.runInContext(idle.match(/onTriggered: ([^\n]*)/)[1], ctx);
  const finish = (submap, ok = true) => { ctx.transition.running = false; ctx.finished(submap, ok); };
  return { ctx, commands, recorded, finish, source, pollRunning, expire };
}

test('accepted chords are published only after leave completes', () => {
  const { ctx, commands, recorded, finish } = recorder();
  ctx.start();
  assert.equal(ctx.operation, 'enter');
  finish('omafind-record');
  ctx.capture(0x48, META);
  assert.equal(ctx.active, false);
  assert.equal(ctx.operation, 'leave');
  assert.equal(commands.length, 2);
  assert.deepEqual(recorded, []);
  finish('');
  assert.deepEqual(recorded, ['SUPER + H']);
  assert.equal(ctx.nonce, '');
});

test('cancel while enter is pending always queues leave', () => {
  const { ctx, commands, recorded, finish } = recorder();
  ctx.start();
  ctx.stop();
  assert.equal(commands.length, 1);
  finish('omafind-record');
  assert.equal(ctx.operation, 'leave');
  assert.equal(commands.length, 2);
  finish('');
  assert.equal(ctx.active, false);
  assert.deepEqual(recorded, []);
});

test('conflicts keep capture active and Escape cancels', () => {
  const { ctx, finish, recorded } = recorder();
  ctx.binds = { 'Super H': 'Hardware' };
  ctx.start();
  finish('omafind-record');
  ctx.capture(0x48, META);
  assert.equal(ctx.conflict, 'Super H is already bound to Hardware in Hyprland. Press another shortcut.');
  assert.equal(ctx.active, true);
  ctx.capture(0x01000021, META);
  assert.equal(ctx.active, true);
  ctx.capture(0x01000000, 0);
  assert.equal(ctx.active, false);
  finish('');
  assert.deepEqual(recorded, []);
});

test('submap polling ignores stale replies and cancels a lost submap', () => {
  const { ctx, finish } = recorder();
  ctx.start();
  ctx.pollSubmap();
  assert.equal(ctx.submapQuery.running, false);
  finish('omafind-record');
  ctx.polledNonce = 'old';
  ctx.checkSubmap('default');
  assert.equal(ctx.active, true);
  ctx.pollSubmap();
  assert.equal(ctx.submapQuery.running, true);
  ctx.checkSubmap('resize');
  assert.equal(ctx.active, false);
  assert.equal(ctx.lost, true);
  assert.equal(ctx.operation, 'leave');
});

test('idle expiry stops the timer and polling, and destruction still cleans up', () => {
  const { ctx, source, finish, pollRunning, expire } = recorder();
  assert.equal(pollRunning(), false);
  ctx.start();
  assert.equal(ctx.limit.restarts, 1);
  assert.equal(pollRunning(), true);
  finish('omafind-record');
  expire();
  assert.equal(ctx.active, false);
  assert.equal(ctx.limit.stops, 1);
  assert.equal(pollRunning(), false);
  const calls = [];
  ctx.Quickshell = { execDetached(command) { calls.push(command); } };
  vm.runInContext(source.match(/Component.onDestruction: \{([^]*?)\n  \}/)[1], ctx);
  assert.equal(calls.length, 1);
  assert.match(calls[0][2], /submap\("reset"\)/);
});

test('every unfinished key press renews the idle limit', () => {
  const { ctx, finish } = recorder();
  ctx.start();
  ctx.capture(0x48, META);
  assert.equal(ctx.limit.restarts, 2);
  finish('omafind-record');
  ctx.capture(0x01000021, META);
  assert.equal(ctx.limit.restarts, 3);
  ctx.capture(0x48, 0);
  assert.equal(ctx.limit.restarts, 4);
  assert.equal(ctx.active, true);
  ctx.capture(0x48, META);
  assert.equal(ctx.active, false);
  assert.equal(ctx.limit.stops, 1);
});

test('capture waits for submap entry and a failed entry cancels', () => {
  const { ctx, recorded, finish } = recorder();
  ctx.start();
  ctx.capture(0x48, META);
  assert.equal(ctx.accepted, '');
  assert.equal(ctx.active, true);
  finish('default');
  assert.equal(ctx.active, false);
  assert.equal(ctx.exposed, true);
  assert.equal(ctx.operation, 'leave');
  finish('');
  assert.deepEqual(recorded, []);
});

test('failed leave retries once, then remains pending for overlay close', () => {
  const { ctx, recorded, commands, finish } = recorder();
  ctx.start();
  finish('omafind-record');
  ctx.capture(0x48, META);
  const nonce = ctx.nonce;
  finish('', false);
  assert.equal(commands.length, 3);
  assert.equal(ctx.operation, 'leave');
  assert.deepEqual(recorded, []);
  finish('', false);
  assert.equal(commands.length, 3);
  assert.equal(ctx.pendingLeave, true);
  assert.equal(ctx.nonce, nonce);
  assert.equal(ctx.accepted, '');
  assert.match(ctx.conflict, /Close setup to retry, or press Super Esc/);
  ctx.start();
  assert.equal(ctx.active, false);
  assert.equal(commands.length, 3);
  ctx.stop();
  assert.equal(commands.length, 4);
  ctx.stop();
  assert.equal(commands.length, 4);
  finish('');
  assert.equal(ctx.pendingLeave, false);
  assert.equal(ctx.nonce, '');
  assert.deepEqual(recorded, []);
});

test('a successful leave retry publishes the accepted chord once', () => {
  const { ctx, recorded, finish } = recorder();
  ctx.start();
  finish('omafind-record');
  ctx.capture(0x48, META);
  finish('', false);
  assert.deepEqual(recorded, []);
  finish('');
  assert.deepEqual(recorded, ['SUPER + H']);
  assert.equal(ctx.pendingLeave, false);
  assert.equal(ctx.nonce, '');
});
