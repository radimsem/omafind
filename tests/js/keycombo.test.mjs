import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
import { plain } from './fixtures.mjs';

const SHIFT = 0x02000000;
const CTRL = 0x04000000;
const ALT = 0x08000000;
const META = 0x10000000;
const KEYPAD = 0x20000000;

test('Qt capture keeps canonical modifiers and key names, and Esc cancels', () => {
  const { comboFromQt, toHyprland, fromHyprland } = load('keycombo.js');
  for (const [key, modifiers, expected] of [
    [0x48, META | SHIFT, ['Super', 'Shift', 'H']],
    [0x48, ALT | SHIFT | CTRL | META | KEYPAD, ['Super', 'Ctrl', 'Shift', 'Alt', 'H']],
    [0x01000001, 0, ['Tab']], [0x01000005, 0, ['Return']], [0x20, META, ['Super', 'Space']],
    [0x01000030, 0, ['F1']], [0x01000052, 0, ['F35']], [0x39, 0, ['9']],
    [0x01000000, CTRL, ['Ctrl', 'Escape']], [0x01000021, CTRL, null],
    [0x01000000, 0, 'cancel'], [0x01000000, META, 'cancel'],
  ]) {
    const result = comboFromQt(key, modifiers);
    assert.deepEqual(plain(result), expected);
    if (Array.isArray(result)) assert.deepEqual(plain(fromHyprland(toHyprland(result))), expected);
  }
});

test('Hyprland strings use uppercase tokens and parse in any modifier order', () => {
  const { toHyprland, fromHyprland, label } = load('keycombo.js');
  assert.equal(toHyprland(['Super', 'Alt', 'I']), 'SUPER + ALT + I');
  assert.deepEqual(plain(fromHyprland(' ALT + SHIFT + SUPER + CTRL + H ')), ['Super', 'Ctrl', 'Shift', 'Alt', 'H']);
  assert.deepEqual(plain(fromHyprland('F9')), ['F9']);
  for (const bad of ['', 'SUPER', 'SUPER + E + D', 'SUPER + F36', 7]) assert.deepEqual(plain(fromHyprland(bad)), []);
  assert.equal(label(['Super', 'Space']), 'Super Space');
});

test('the bind map keeps the first description per chord', () => {
  const { bindMap } = load('keycombo.js');
  assert.deepEqual(plain(bindMap([{ chord: 'Super D', description: 'Files' },
    { chord: 'Super D', description: 'Second' }, { chord: 'F9', description: '' },
    { chord: 'constructor', description: 'Odd' }])),
  { 'Super D': 'Files', F9: '', constructor: 'Odd' });
  assert.deepEqual(plain(bindMap(null)), {});
});

test('a captured chord needs Super or a function key and must be free in Hyprland', () => {
  const { checkCombo } = load('keycombo.js');
  const binds = { 'Super Ctrl H': 'Hardware menu', 'Super H': '', 'Ctrl F9': 'Dictation' };
  for (const [parts, expected] of [
    [['Ctrl', 'K'], 'Ctrl K would fire while you type. Add Super and try again.'],
    [['Super', 'Ctrl', 'H'], 'Super Ctrl H is already bound to Hardware menu in Hyprland. Press another shortcut.'],
    [['Super', 'H'], 'Super H is already bound in Hyprland. Press another shortcut.'],
    [['Super', '1'], 'Super 1 is already bound in Hyprland. Press another shortcut.'],
    [['Ctrl', 'F9'], 'Ctrl F9 would fire while you type. Add Super and try again.'],
    [['F9'], null], [['Super', 'E'], null], [['Super', 'Constructor'], null],
  ]) assert.equal(checkCombo(parts, binds), expected);
});

test('submap loss stops only a recording whose enter has finished', () => {
  const { recordingSubmapLost } = load('keycombo.js');
  for (const [active, operation, submap, expected] of [
    ['shortcut', 'entered', 'default\n', true], ['shortcut', 'entered', 'resize', true],
    ['shortcut', 'entered', '', true], ['shortcut', 'entered', 'omafind-record\n', false],
    ['shortcut', 'enter', 'default', false], ['shortcut', 'leave', 'default', false],
    ['', 'entered', 'default', false],
  ]) assert.equal(recordingSubmapLost(active, operation, submap), expected);
});

test('the record command names omafind submap, lock and watchdog', () => {
  const { recordCommand } = load('keycombo.js');
  const enter = recordCommand('n1', false);
  const leave = recordCommand('n1', true);
  assert.deepEqual(plain(enter.slice(0, 2)), ['sh', '-c']);
  assert.deepEqual(plain(enter.slice(-2)), ['omafind-record', 'n1']);
  assert.deepEqual(plain(leave.slice(-2)), ['omafind-record', 'n1']);
  assert.match(enter[2], /\$\{XDG_RUNTIME_DIR:\?\}\/omafind-record/);
  assert.match(enter[2], /hl\.dsp\.submap\("omafind-record"\)/);
  assert.match(enter[2], /omafind-watchdog/);
  assert.match(enter[2], /sleep 31/);
  assert.match(leave[2], /hl\.dsp\.submap\("reset"\)/);
  assert.doesNotMatch(enter[2] + leave[2], /omaone/);
});
