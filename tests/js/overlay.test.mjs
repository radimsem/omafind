import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { load } from './load.mjs';
import { plain } from './fixtures.mjs';

const timer = () => ({ running: false, restart() { this.running = true; }, stop() { this.running = false; } });

function overlay(values = {}) {
  const shown = [];
  const ctx = vm.createContext({ Errors: load('errors.js'), pendingOpen: null, failedOpen: null,
    opened: false, service: null, searchView: { flash: 'acc' }, closeTimer: timer(), openTimeout: timer(),
    toast: { dismissed: 0, showError(error) { shown.push(error); }, dismiss() { this.dismissed++; } },
    ...values });
  ctx.root = ctx;
  const source = readFileSync(new URL('../../ui/Overlay.qml', import.meta.url), 'utf8');
  for (const match of source.matchAll(/^  function \w+\([^]*?^  \}/gm)) vm.runInContext(match[0], ctx);
  return { ctx, shown };
}

const item = { id: 'pdf:1', name: 'a.pdf' };
const message = { t: 'open', id: 'pdf:1', how: 'open', line: 12 };
const notConnected = { code: 'drive-not-mounted', title: 'Photos2024 is not connected.',
  detail: 'Connect it, then press Retry.', fix: { kind: 'retry' } };

test('error replies give the toast only the error fields', () => {
  const { Errors } = overlay().ctx;
  assert.deepEqual(plain(Errors.from({ t: 'error', id: 'pdf:1', for: 'open', code: 'open-failed',
    title: 'a.pdf could not be opened.', detail: 'Permission denied.', fix: { kind: 'retry' } })),
  { code: 'open-failed', title: 'a.pdf could not be opened.', detail: 'Permission denied.', fix: { kind: 'retry' } });
  assert.deepEqual(plain(Errors.from({ t: 'open_failed', id: 'pdf:1', error: notConnected })), notConnected);
  assert.deepEqual(plain(Errors.from({ t: 'open_failed', id: 'pdf:1', reason: 'missing' })),
    { code: 'unknown', title: 'missing', detail: '' });
  assert.equal(Errors.from({ t: 'discover_counts', root: '/h' }), null);
});

test('a failed open shows the error and keeps the request for Retry', () => {
  const { ctx, shown } = overlay({
    pendingOpen: { id: 'pdf:1', how: 'open', item, message, reply: null, closed: false } });
  ctx.closeTimer.running = true;
  ctx.openTimeout.running = true;
  ctx.failOpen(notConnected);
  assert.equal(ctx.pendingOpen, null);
  assert.equal(ctx.searchView.flash, '');
  assert.equal(ctx.closeTimer.running, false);
  assert.equal(ctx.openTimeout.running, false);
  assert.deepEqual(plain(shown), [notConnected]);
  assert.deepEqual(plain(ctx.failedOpen), { message, item, how: 'open' });
});

test('Retry sends the same open again and announces it as a first open', () => {
  const sent = [];
  const { ctx } = overlay({ service: { send(m) { sent.push(m); return true; } },
    failedOpen: { message, item, how: 'open' } });
  ctx.retryOpen();
  assert.deepEqual(plain(sent), [message]);
  assert.equal(ctx.toast.dismissed, 1);
  assert.equal(ctx.failedOpen, null);
  assert.deepEqual(plain(ctx.pendingOpen),
    { id: 'pdf:1', how: 'open', item, message, reply: null, closed: true });
  assert.equal(ctx.openTimeout.running, true);
  assert.equal(ctx.closeTimer.running, false);
});

test('Retry with the overlay open closes it as a first open does', () => {
  const { ctx } = overlay({ opened: true, service: { send() { return true; } },
    failedOpen: { message, item, how: 'open' } });
  ctx.retryOpen();
  assert.equal(ctx.pendingOpen.closed, false);
  assert.equal(ctx.closeTimer.running, true);
});

test('Retry does nothing when the request cannot be sent', () => {
  const { ctx } = overlay({ service: { send() { return false; } }, failedOpen: { message, item, how: 'open' } });
  ctx.retryOpen();
  assert.equal(ctx.pendingOpen, null);
  assert.equal(ctx.toast.dismissed, 1);
});
