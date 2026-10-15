import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, symlinkSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { load } from './load.mjs';

function runtime(t) {
  const dir = mkdtempSync(join(tmpdir(), 'omafind-record-test-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const bin = join(dir, 'bin');
  mkdirSync(bin);
  for (const name of ['sh', 'cat', 'rm', 'flock']) {
    const found = spawnSync('sh', ['-c', 'command -v "$1"', 'lookup', name], { encoding: 'utf8' });
    if (found.status !== 0) {
      t.skip(`${name} is unavailable`);
      return null;
    }
    symlinkSync(found.stdout.trim(), join(bin, name));
  }
  function fake(name, source) { writeFileSync(join(bin, name), '#!/bin/sh\n' + source, { mode: 0o755 }); }
  fake('hyprctl', `printf '%s\\n' "$*" >> "$XDG_RUNTIME_DIR/calls"
case "$1" in
  binds) printf '[]' ;;
  eval) if [ ! -e "$XDG_RUNTIME_DIR/eval-missing" ]; then : > "$XDG_RUNTIME_DIR/escape"; fi ;;
  submap) cat "$XDG_RUNTIME_DIR/submap" ;;
  dispatch)
    if [ -e "$XDG_RUNTIME_DIR/fail" ]; then exit 1; fi
    if [ -e "$XDG_RUNTIME_DIR/no-change" ]; then exit 0; fi
    case "$2" in *reset*) printf default > "$XDG_RUNTIME_DIR/submap" ;;
      *) printf omafind-record > "$XDG_RUNTIME_DIR/submap" ;; esac ;;
esac
`);
  fake('jq', 'cat >/dev/null\n[ -e "$XDG_RUNTIME_DIR/escape" ]\n');
  fake('setsid', 'printf "%s" "$4" > "$XDG_RUNTIME_DIR/watchdog"\n');
  fake('sleep', 'printf "%s" "$1" > "$XDG_RUNTIME_DIR/delay"\n');
  writeFileSync(join(dir, 'submap'), 'default');
  const { recordCommand } = load('keycombo.js');
  function run(argv, expected = 0) {
    const result = spawnSync(join(bin, argv[0]), Array.from(argv).slice(1), {
      env: { PATH: bin, XDG_RUNTIME_DIR: dir }, encoding: 'utf8',
    });
    assert.equal(result.status, expected, result.stderr);
  }
  return { dir, run, recordCommand, read(name) { return readFileSync(join(dir, name), 'utf8'); } };
}

test('enter and leave use only fake Hyprland and restore the default submap', t => {
  const r = runtime(t);
  if (!r) return;
  r.run(r.recordCommand('n1', false));
  assert.equal(r.read('submap'), 'omafind-record');
  assert.equal(r.read('omafind-record'), 'n1\n');
  r.run(r.recordCommand('n1', true));
  assert.equal(r.read('submap'), 'default');
  assert.equal(existsSync(join(r.dir, 'omafind-record')), false);
});

test('an early leave cancels its pending enter and stale cleanup preserves a newer owner', t => {
  const r = runtime(t);
  if (!r) return;
  r.run(r.recordCommand('early', true));
  r.run(r.recordCommand('early', false));
  assert.equal(r.read('submap'), 'default');
  assert.equal(existsSync(join(r.dir, 'omafind-record')), false);
  r.run(r.recordCommand('new', false));
  r.run(r.recordCommand('old', true));
  assert.equal(r.read('submap'), 'omafind-record');
  assert.equal(r.read('omafind-record'), 'new\n');
});

test('the watchdog cleans up with a fake sleep and preserves another active submap', t => {
  const r = runtime(t);
  if (!r) return;
  r.run(r.recordCommand('n1', false));
  r.run(['sh', '-c', r.read('watchdog'), 'omafind-watchdog', 'n1']);
  assert.equal(r.read('delay'), '31');
  assert.equal(r.read('submap'), 'default');
  r.run(r.recordCommand('n2', false));
  writeFileSync(join(r.dir, 'submap'), 'resize');
  r.run(r.recordCommand('n2', true));
  assert.equal(r.read('submap'), 'resize');
});


test('failed submap reset retains the lock owner for watchdog cleanup', t => {
  const r = runtime(t);
  if (!r) return;
  r.run(r.recordCommand('n1', false));
  writeFileSync(join(r.dir, 'fail'), '');
  r.run(r.recordCommand('n1', true), 1);
  assert.equal(r.read('omafind-record'), 'n1\n');
  rmSync(join(r.dir, 'fail'));
  r.run(['sh', '-c', r.read('watchdog'), 'omafind-watchdog', 'n1']);
  assert.equal(r.read('submap'), 'default');
});

for (const missing of [false, true]) {
  test(`eval must install the Escape bind before entry (missing=${missing})`, t => {
    const r = runtime(t);
    if (!r) return;
    if (missing) writeFileSync(join(r.dir, 'eval-missing'), '');
    r.run(r.recordCommand('n1', false), missing ? 1 : 0);
    assert.equal(r.read('submap'), missing ? 'default' : 'omafind-record');
    assert.equal(r.read('calls').includes('dispatch'), !missing);
    assert.equal(r.read('calls').split('\n').filter(line => line === 'binds -j').length, 2);
  });
}

test('a reset that returns success without leaving fails and retains its owner', t => {
  const r = runtime(t);
  if (!r) return;
  r.run(r.recordCommand('n1', false));
  writeFileSync(join(r.dir, 'no-change'), '');
  r.run(r.recordCommand('n1', true), 1);
  assert.equal(r.read('submap'), 'omafind-record');
  assert.equal(r.read('omafind-record'), 'n1\n');
  rmSync(join(r.dir, 'no-change'));
  r.run(r.recordCommand('n1', true));
  assert.equal(r.read('submap'), 'default');
});
