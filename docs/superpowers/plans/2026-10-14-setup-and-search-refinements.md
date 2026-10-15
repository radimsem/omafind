# Setup and Search Refinements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix what the owner's smoke test of setup and search found: a lazy, fast Folders step that indexes every checked folder, shortcut capture ported from omaone, sharp text, full-resolution previews, open-at-line, and terminal-style result keys.

**Architecture:** The daemon replaces the up-front candidate scan with a one-level `discover_start`, a background `fd` walk per root that streams rolled-up counts as `discover_counts`, and a one-level `discover_children`. The overlay keeps the selection as two absolute path sets in `lib/tree.js` and draws one `ListView` tree (`ui/FolderTree.qml`) shared by the Folders step and the drive dialog. Search fixes stay in their existing files (`lib/keys.js`, `lib/results.js`, `SearchView.qml`, `ipc.py`, `preview.py`); shortcut capture reuses omaone's `keycombo.js` logic with a new read-only `binds_get` request.

**Tech Stack:** Python 3 asyncio daemon (`helper/omafindd`), pytest, `fd`, `magick`, `pdftoppm`; QML on Quickshell (Qt 6), `.pragma library` JS tested with `node --test`.

**Spec:** `docs/superpowers/specs/2026-10-14-setup-and-search-refinements-design.md`

## Global Constraints

- Work in `/home/radimsem/personal/projects/omafind-wt/setup-search-refinements` on branch `fix/setup-and-search-refinements`. Never commit on main.
- Commits are Conventional Commits, subject only (one `-m`, no body, no trailers), at most 72 characters. Scopes: `omafindd`, `overlay`, `setup`, `search`, `cli`. Implementation and its tests go in the same commit.
- Every task that adds or changes an IPC message or a settings key updates `docs/ipc.md`, `settings.example.json`, `helper/omafindd/settings.py`, `lib/Settings.js` and the README table in that same task.
- No change to the settings shape: `roots` with `excludes` and `codeRoots` stay as they are. No change to indexing, embedding or ranking.
- Read `docs/DESIGN.md` before touching any QML surface. The type floor after Task 1: "The minimum size is 11 px. 10 px is allowed only for bold uppercase headers."
- New copy is sentence case, straight quotes, no em or en dashes in prose, no exclamation marks, none of the banned words (seamless, leverage, robust, comprehensive, delve, showcase, crucial, streamline, unlock, ...). New strings: "Press a shortcut", "<Chord> is already bound to <description> in Hyprland. Press another shortcut.", "Indexing finished", "Indexing stopped".
- Light checks, no memory cap needed:
  - `uv run --project helper pytest -q <path>` (full suite: `uv run --project helper pytest -q`)
  - `node --test tests/js/<file>.test.mjs` (all: `node --test "tests/js/*.test.mjs"`)
  - `scripts/qmllint.sh`
  - `uv run --project helper ruff check helper tests bin/omafind scripts`
- Heavy jobs (a dev daemon, `llama-server`, `scripts/probe.py`, torch) run one at a time inside `systemd-run --user --scope --quiet --collect -p MemoryMax=8G -p MemorySwapMax=0 -- <command>`. Only Task 17 runs one. `pgrep -x llama-server` must be empty at the end.
- Never touch the live `omafind.service`, `~/.config/omarchy/shell.json` or anything in `~/.config`. Never inject keys (`wtype`) into the live desktop. Never `pkill -f` a script from the same shell call that names it.
- Baseline before Task 1: 834 pytest pass (1 deselected), 143 node tests pass, qmllint exit 0, ruff clean.
- The Folders step does not work at runtime between Task 9 (daemon switch) and Task 12 (new UI). The branch lands as one pull request; every commit still passes the automated checks.

## Review Focus

1. A walk that fails (fd missing, a root that vanished, a permission error at the root) must end with a `done` batch carrying `error`, and the Folders step must show the error and stop its spinners instead of spinning forever. Pinned in Task 9 (`test_walk_failure_ends_with_done_and_error`) and Task 12 (header uses `Setup.walkError`).
2. Opening setup a second time, or the drive dialog, while a walk runs must reuse that walk and replay its counts, not start a second `fd` over the same root. Pinned in Task 9 (`test_repeat_discover_start_reuses_walk_and_replays_counts`).
3. Symlinked, unreadable or vanished folders must never crash `discover_start` or `discover_children`; they are hidden or reported with an `error` field. Pinned in Task 8 (`test_folders_hide_symlinks_hidden_heavy_and_secrets`, `test_children_of_unreadable_folder_report_error`).
4. A home with hundreds of top-level folders must paint at once: `top` caps the list at 500 rows and reads one level only. Pinned in Task 8 (`test_top_caps_rows_at_limit`).
5. Ctrl+C with a selection in the query copies the selected text, not the result path; Esc with the progress popover open closes the popover, not the overlay. Pinned in Task 2 (`Ctrl C with a query selection is left to the text field`) and Task 5 (key action `progress`, Esc order in `SearchView.handleKey`).

---

## File Structure

Daemon (`helper/omafindd`):
- `discovery.py`: lazy discovery. `top()` reads one level per root, `folders()` lists visible child folders, `Walk` runs one `fd` pass and rolls counts up, `children()` answers one level, `snapshot()` feeds the CLI, `device()` picks the estimate device. The old scan, tree, candidate and repo code is deleted.
- `rules.py`: `datasets()` becomes media-only with evidence; `keep()` stops dropping datasets. `removed`, `explain`, `rule_dirs`, `secret_family` are deleted.
- `setup.py`: `SetupService` gains `discover_children`, `index_progress`, `binds_get`, walk lifecycle; loses `discover_tree` and the scan cache.
- `ipc.py`: keeps preview jumps across a meaning-leg reply; `open` takes `line`.
- `preview.py`: images return the original or a cached `magick` still; PDF renders at 1200 px.
- `bindings.py`: `binds_items()` for `binds_get`; `first_free()` deleted.
- `settings.py`: `valid_shortcut` accepts a lone `F1` to `F35`.
- `leftout.py`: deleted.

Overlay:
- `ui/Label.qml` (new): the one sharp static text type.
- `ui/KindProgress.qml` (new): per-kind progress rows, used by the Index step and the search popover.
- `ui/FolderTree.qml` (new): the lazy folder `ListView`, used by `SetupFolders.qml` and `DriveDialog.qml`.
- `ui/ShortcutRow.qml` (new): keycaps, the "Press a shortcut" prompt and the Change/Cancel button.
- `ui/ShortcutRecorder.qml` (new): the `omafind-record` submap transitions, polling and the 30 s limit.
- `lib/keycombo.js` (new): chord capture, Hyprland strings, conflict sentence, record command.
- `lib/tree.js`: rewritten around `{chosen, skipped, code}` absolute path sets.
- `lib/keys.js`, `lib/results.js`, `lib/searchState.js`, `lib/setup.js`: key, fold, latency, title and facts helpers.
- `Service.qml`: discovery caches, `requestChildren`, `requestProgress`, `getBinds`; the binding-check processes go.
- Deleted: `ui/LeftOutLedger.qml`, `ui/SetupLeaveOut.qml`, `ui/LedgerFooter.qml`, `ui/KindBar.qml`, `ui/Hatch.qml`, `lib/ledger.js`, `tests/js/ledger.test.mjs`, `lib/ledgerTree.js` (a temporary copy made in Task 10), `tests/js/ledgerTree.test.mjs`, `tests/fixtures/setup/documents-tree.json`, `tests/helper/test_leftout.py`.

---

### Task 1: Sharp text

**Files:**
- Create: `ui/Label.qml`
- Create: `tests/helper/test_qml_text.py`
- Modify: every `ui/*.qml` that declares a static `Text` (sed below), `Tokens.qml:43-47`, `ui/RuleTag.qml:40-47`, `ui/FolderRow.qml:255,288,302-303`, `ui/Facts.qml:10`, `ui/SetupFacts.qml:11`, `ui/SetupKey.qml:10`, `ui/KeyCap.qml:24`, `ui/FolderTable.qml:75-77`, `ui/SetupFolders.qml:272,285`, `ui/SetupHeader.qml:114`, `ui/QueryRow.qml:91`, `docs/DESIGN.md:118-120,250`

**Interfaces:**
- Produces: `Label` (a `Text` with `renderType: Text.NativeRendering`, `textFormat: Text.PlainText`, `color: Plugin.Tokens.fg2`, `font.family: Style.font.family`, `font.pixelSize: Style.font.bodySmall` as defaults). Every later task writes static text as `Label { ... }`, never `Text { ... }`.
- Produces: `Plugin.Tokens.tiny` and `Plugin.Tokens.tagTracking` no longer exist. `Style.font.caption` is used only in `ui/SectionHeader.qml`'s bold title.

- [ ] **Step 1: Write the failing test**

`tests/helper/test_qml_text.py`:

```python
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QML = sorted([*ROOT.glob("*.qml"), *(ROOT / "ui").glob("*.qml")])
TEXT = re.compile(r"^\s*(?:delegate:\s*|component \w+:\s*)?Text\s*\{", re.MULTILINE)


def test_static_text_goes_through_label():
    owners = {path.relative_to(ROOT).as_posix(): len(TEXT.findall(path.read_text()))
              for path in QML}
    assert {name: n for name, n in owners.items() if n} == {"ui/Label.qml": 1,
                                                            "ui/QueryRow.qml": 1}


def test_small_sizes_only_in_bold_uppercase_headers():
    users = [path.relative_to(ROOT).as_posix() for path in QML
             if re.search(r"Style\.font\.caption|Tokens\.tiny", path.read_text())]
    assert users == ["ui/SectionHeader.qml"]


def test_letter_spacing_is_whole_pixels():
    lines = [line.strip() for path in QML for line in path.read_text().splitlines()
             if "letterSpacing" in line]
    assert lines
    assert all("Math.round(" in line for line in lines)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project helper pytest -q tests/helper/test_qml_text.py`
Expected: FAIL, all three tests (many files own `Text`, many use `caption`, spacing is not rounded).

- [ ] **Step 3: Create `ui/Label.qml`**

```qml
import QtQuick
import qs.Commons
import ".." as Plugin

// Static text drawn with the platform rasterizer, so glyphs sit on whole pixels at scale 1.
// Text inputs keep their own rendering.
Text {
  renderType: Text.NativeRendering
  textFormat: Text.PlainText
  color: Plugin.Tokens.fg2
  font.family: Style.font.family
  font.pixelSize: Style.font.bodySmall
}
```

- [ ] **Step 4: Rename every static `Text` to `Label`**

```bash
sed -i -E 's/^(\s*)(delegate: |component (\w+): )?Text \{/\1\2Label {/' ui/*.qml
```

Then restore the one `Text` that mirrors the query field. In `ui/QueryRow.qml` change the element at line 91 back and add a comment:

```qml
    // Mirrors the TextInput glyph for glyph, so it keeps the input's rendering.
    Text {
      id: styled
```

`Overlay.qml`, `SearchView.qml`, `SetupView.qml`, `Service.qml`, `Palette.qml` and `Tokens.qml` declare no `Text`; leave them. `ui/Label.qml` itself keeps `Text {` as its root.

- [ ] **Step 5: Raise the small sizes**

```bash
sed -i 's/Style\.font\.caption/Style.font.bodySmall/g' $(grep -l 'Style\.font\.caption' ui/*.qml | grep -v SectionHeader.qml)
```

In `ui/SectionHeader.qml` keep the bold uppercase title at `Style.font.caption` (line 28) and change the count below it (line 38) to `Style.font.bodySmall`.

In `ui/FolderRow.qml` lines 302-303 replace `fontSize: Plugin.Tokens.tiny` with `fontSize: Style.font.bodySmall`.

In `ui/RuleTag.qml` replace lines 44-46 with:

```qml
      font.pixelSize: Style.font.bodySmall
      font.capitalization: Font.AllUppercase
      font.letterSpacing: Math.round(Style.font.bodySmall * Plugin.Tokens.tracking)
```

In `ui/LeftOutLedger.qml` lines 119-121 apply the same three lines (the file goes in Task 13, it must still lint until then).

In `Tokens.qml` replace lines 43-47 with:

```qml
  // Tracking of uppercase headers in em, rounded to whole pixels where used.
  readonly property real tracking: 0.08
```

- [ ] **Step 6: Round the remaining letter spacing**

```bash
sed -i -E 's/font\.letterSpacing: (.*)$/font.letterSpacing: Math.round(\1)/' ui/*.qml
grep -n letterSpacing ui/*.qml
```

Expected: every line reads `font.letterSpacing: Math.round(...)` with no double wrap. The SectionHeader title becomes `Math.round(Style.font.caption * 0.1)`, which is 1 px.

- [ ] **Step 7: Update the type table in `docs/DESIGN.md`**

Replace rows 118-120 with:

```markdown
| 10 | `caption` | Bold uppercase section headers only |
| 11 | `bodySmall` | Table headers, badges, fact tokens, rule tags, key caps, folder line, footer, why line, meta, status, hints |
```

and in line 250 replace "11 px in the preview, 10 px elsewhere" with "11 px". Add one line under the table: "Static text uses `ui/Label.qml` (native rendering). Letter spacing is rounded to whole pixels."

- [ ] **Step 8: Run the checks**

Run: `uv run --project helper pytest -q tests/helper/test_qml_text.py && scripts/qmllint.sh && node --test "tests/js/*.test.mjs"`
Expected: 3 passed; qmllint exit 0; 143 node tests pass.

- [ ] **Step 9: Commit**

```bash
git add ui Tokens.qml docs/DESIGN.md tests/helper/test_qml_text.py
git commit -m "fix(overlay): draw static text natively at 11 px and above"
```

---

### Task 2: Result keys

**Files:**
- Modify: `lib/keys.js:6-53`, `lib/results.js` (add `jump` after `move`), `SearchView.qml:168-174,183-196,240-280,526`, `ui/Footer.qml:204`
- Test: `tests/js/keys.test.mjs`, `tests/js/results.test.mjs`

**Interfaces:**
- Produces: `KeyMap.action(event, ctx)` with `ctx = {query, row, selection}` returns one of `clear, close, up, down, pageup, pagedown, first, last, open, reveal, expand, play, copy, progress` or `null`. (`progress` is added in Task 5; `expand` becomes `toggle-weak` in Task 6.)
- Produces: `KeyMap.hints(row, jump)` returns `[{keys, label}]`; the `dim` field is gone.
- Produces: `Results.jump(rows, index, steps)` returns the selectable row index `steps` selectable rows away, clamped to the first and last; `steps` may be negative, `Infinity` or `-Infinity`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/js/keys.test.mjs`:

```js
test('Ctrl N and P move, page keys page, and Ctrl Home and End jump to the ends', () => {
  const { action } = load('format.js', 'keys.js');
  const CTRL = 0x04000000;
  for (const [key, modifiers, want] of [[0x4e, CTRL, 'down'], [0x50, CTRL, 'up'],
    [0x4e, 0, null], [0x50, 0, null],
    [0x01000017, 0, 'pagedown'], [0x01000016, 0, 'pageup'],
    [0x01000010, CTRL, 'first'], [0x01000011, CTRL, 'last'],
    [0x01000010, 0, null], [0x01000011, 0, null]]) {
    assert.equal(action({ key, text: '', modifiers }, { query: 'q', row: null }), want);
  }
});

test('Ctrl C with a query selection is left to the text field', () => {
  const { action } = load('format.js', 'keys.js');
  const row = freeze({ type: 'item', item: fixture('pdf').items[0] });
  const ctrlC = { key: 0x43, modifiers: 0x04000000 };
  assert.equal(action(ctrlC, { row, selection: true }), null);
  assert.equal(action(ctrlC, { row, selection: false }), 'copy');
});
```

Replace the test `hints follow jump targets with dim preview hints for non-playable kinds` with:

```js
test('hints follow jump targets and offer Ctrl Space only for audio and video', () => {
  const { hints } = load('format.js', 'keys.js');
  for (const [kind, open, play] of [['image', 'open', null],
    ['video', 'open at 14:32', 'play at 14:32'],
    ['audio', 'open at 7:55', 'play at 7:55'],
    ['pdf', 'open at page 12', null], ['text', 'open at line 41', null],
    ['code', 'open at line 8', null]]) {
    const want = [{ keys: ['Enter'], label: open },
      { keys: ['Ctrl', 'Enter'], label: 'show in folder' }];
    if (play) want.push({ keys: ['Ctrl', 'Space'], label: play });
    want.push({ keys: ['Ctrl', 'C'], label: 'copy path' }, { keys: ['Esc'], label: 'close' });
    assert.deepEqual(plain(hints(freeze({ type: 'item', item: fixture(kind).items[0] }))), want);
  }
  assert.deepEqual(plain(hints({ type: 'item', item: fixture('offline').items[0] })), [
    { keys: ['Ctrl', 'C'], label: 'copy path' }, { keys: ['Esc'], label: 'close' }
  ]);
  assert.deepEqual(plain(hints({ type: 'weak' })), [
    { keys: ['Enter'], label: 'expand' }, { keys: ['Esc'], label: 'close' }
  ]);
  assert.deepEqual(plain(hints(null)), [{ keys: ['Esc'], label: 'close' }]);
});
```

Append to `tests/js/results.test.mjs`:

```js
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test tests/js/keys.test.mjs tests/js/results.test.mjs`
Expected: FAIL (`pagedown` is null, hints carry `dim`, `jump is not a function`).

- [ ] **Step 3: Implement keys**

In `lib/keys.js` replace the `K` table and `action`:

```js
var K = {Key_Escape: 0x01000000, Key_Return: 0x01000004, Key_Enter: 0x01000005,
  Key_Up: 0x01000013, Key_Down: 0x01000015, Key_PageUp: 0x01000016, Key_PageDown: 0x01000017,
  Key_Home: 0x01000010, Key_End: 0x01000011, Key_Space: 0x20, Key_J: 0x4a,
  Key_K: 0x4b, Key_C: 0x43, Key_N: 0x4e, Key_P: 0x50, ControlModifier: 0x04000000,
  AltModifier: 0x08000000, ShiftModifier: 0x02000000}

function action(event, ctx) {
  var key = event.key
  var ctrl = (event.modifiers & K.ControlModifier) !== 0
  var alt = (event.modifiers & K.AltModifier) !== 0
  if (key === K.Key_Escape) return ctx.query ? "clear" : "close"
  if (key === K.Key_Up || ((ctrl || alt) && key === K.Key_K) || (ctrl && key === K.Key_P)) return "up"
  if (key === K.Key_Down || ((ctrl || alt) && key === K.Key_J) || (ctrl && key === K.Key_N)) return "down"
  if (key === K.Key_PageUp) return "pageup"
  if (key === K.Key_PageDown) return "pagedown"
  if (ctrl && key === K.Key_Home) return "first"
  if (ctrl && key === K.Key_End) return "last"
  var row = ctx.row
  if (!row) return null
  var enter = key === K.Key_Return || key === K.Key_Enter
  if (row.type === "weak") return enter && !ctrl ? "expand" : null
  if (row.type !== "item") return null
  var item = row.item
  // A selection in the query is the field's to copy.
  if (ctrl && key === K.Key_C) return ctx.selection ? null : "copy"
  if (item.offline) return null
  if (enter) return ctrl ? "reveal" : "open"
  if (ctrl && key === K.Key_Space && (item.kind === "audio" || item.kind === "video")) return "play"
  return null
}
```

Replace `hints`:

```js
function hints(row, jump) {
  var close = {keys: ["Esc"], label: "close"}
  if (!row || row.type === "header") return [close]
  if (row.type === "weak") return [{keys: ["Enter"], label: "expand"}, close]
  var copy = {keys: ["Ctrl", "C"], label: "copy path"}
  var item = row.item
  if (item.offline) return [copy, close]
  var line = jump != null ? jump
    : item.kind === "code" && item.open_line != null ? item.open_line : item.loc
  var target = F.at(item)
  if ((item.kind === "text" || item.kind === "code") && line != null) target = "L" + line
  var open = "open"
  if (target) {
    if (item.kind === "pdf") open += " at page " + item.loc
    else if (item.kind === "text" || item.kind === "code") open += " at line " + line
    else open += " at " + target
  }
  var result = [{keys: ["Enter"], label: open}, {keys: ["Ctrl", "Enter"], label: "show in folder"}]
  if (item.kind === "audio" || item.kind === "video") result.push({keys: ["Ctrl", "Space"], label: "play at " + target})
  return result.concat([copy, close])
}
```

In `lib/results.js` add after `move`:

```js
// The selectable row `steps` selectable rows away from `index`, clamped to the list.
function jump(rows, index, steps) {
  var indexes = selectable(rows)
  if (!indexes.length) return -1
  var at = indexes.indexOf(index)
  if (at < 0) return indexes[0]
  var target = Math.max(0, Math.min(indexes.length - 1, at + steps))
  return indexes[target]
}
```

`at + Infinity` is `Infinity`, and `Math.min` clamps it, so the ends need no special case.

- [ ] **Step 4: Wire the keys in `SearchView.qml`**

Add after `move(delta)` (line 174):

```qml
  function jumpBy(steps) {
    var next = Results.jump(rows, selectedIndex, steps)
    if (next !== selectedIndex) {
      selectedIndex = next
      userMoved = true
    }
  }

  // One visible page of 56 px rows, less one row of overlap.
  function pageSize() {
    return Math.max(1, Math.floor(list.height / Plugin.Tokens.rowHeight) - 1)
  }
```

In `handleKey` pass the selection and handle the new actions:

```qml
    var action = KeyMap.action({key: event.key, text: event.text, modifiers: event.modifiers},
      {query: search.query, row: selectedRow, selection: query.input.selectedText !== ""})
```

and add cases after `case "down":`:

```qml
    case "pageup":
      jumpBy(-pageSize())
      break
    case "pagedown":
      jumpBy(pageSize())
      break
    case "first":
      jumpBy(-Infinity)
      break
    case "last":
      jumpBy(Infinity)
      break
```

In `hintsFor`, delete nothing (it never read `dim`). At line 526 change the idle hints to `[{keys: ["Esc"], label: "close"}]`.

In `ui/Footer.qml` delete line 204 (`opacity: modelData.dim ? 0.4 : 1`).

- [ ] **Step 5: Run the checks**

Run: `node --test tests/js/keys.test.mjs tests/js/results.test.mjs && scripts/qmllint.sh`
Expected: PASS; qmllint exit 0.

- [ ] **Step 6: Commit**

```bash
git add lib/keys.js lib/results.js SearchView.qml ui/Footer.qml tests/js/keys.test.mjs tests/js/results.test.mjs
git commit -m "feat(search): move through results with ctrl n/p and page keys"
```

---

### Task 3: Open at the matched line

**Files:**
- Modify: `helper/omafindd/ipc.py:38-40,154-156,163-212,217-261`, `SearchView.qml:225-238`, `docs/ipc.md:141,153-154`
- Test: `tests/helper/test_ipc_overlay.py`

**Interfaces:**
- Produces: request `{"t":"open","id":str,"how":"open"|"reveal","line":int>=1 (optional)}`. Line order: client `line` (text and code only), then the stored preview jump, then the item's `loc`. A `line` that is not an int ≥ 1 (bools included) replies `{"t":"error","id":id,"for":"open","code":"bad-request","reason":"Invalid open arguments"}`.
- Produces: stored jumps survive a `results` reply whose `seq` equals the previous one, for ids still present.

- [ ] **Step 1: Write the failing tests**

Append to `tests/helper/test_ipc_overlay.py`:

```python
async def test_meaning_leg_keeps_jump_and_new_seq_drops_it(server, tmp_path, monkeypatch):
    path = tmp_path / "a.txt"
    path.touch()
    item = {"id": "hit", "kind": "text", "path": str(path), "loc": 205}
    other = {"id": "gone", "kind": "text", "path": str(path), "loc": 1}
    replies = []

    async def handle(message):
        return replies.pop(0)

    server.service = SimpleNamespace(handle=handle)
    writer = Writer()
    replies.append({"t": "results", "seq": 4, "legs": ["words"], "items": [item, other]})
    await server.dispatch(writer, {"t": "search", "seq": 4})
    monkeypatch.setattr(preview, "render", lambda value, query: {
        "t": "preview", "id": value["id"], "jump": 212, "mode": "lines"})
    await server.dispatch(writer, {"t": "preview", "id": "hit", "q": "talk"})
    await server.dispatch(writer, {"t": "preview", "id": "gone", "q": "talk"})
    replies.append({"t": "results", "seq": 4, "legs": ["words", "meaning"], "items": [item]})
    await server.dispatch(writer, {"t": "search", "seq": 4})
    assert server._jumps[writer] == {"hit": 212}
    replies.append({"t": "results", "seq": 5, "legs": ["words"], "items": [item]})
    await server.dispatch(writer, {"t": "search", "seq": 5})
    assert server._jumps.get(writer, {}) == {}


async def test_open_prefers_client_line_and_rejects_bad_lines(server, tmp_path, monkeypatch):
    path = tmp_path / "a.txt"
    path.touch()
    writer = Writer()
    server._results[writer] = {"hit": {"id": "hit", "kind": "text", "path": str(path), "loc": 205}}
    server._jumps[writer] = {"hit": 212}
    calls = []
    monkeypatch.setattr(opener, "launch", lambda item, **kw: calls.append(item))
    await server.dispatch(writer, {"t": "open", "id": "hit", "how": "open", "line": 230})
    assert calls[-1]["loc"] == 230
    await server.dispatch(writer, {"t": "open", "id": "hit", "how": "open"})
    assert calls[-1]["loc"] == 212
    for line in (0, -3, "7", True, 2.5):
        await server.dispatch(writer, {"t": "open", "id": "hit", "how": "open", "line": line})
        assert writer.messages[-1] == {"t": "error", "id": "hit", "for": "open",
                                       "code": "bad-request", "reason": "Invalid open arguments"}
    assert len(calls) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project helper pytest -q tests/helper/test_ipc_overlay.py`
Expected: FAIL (`_jumps` is popped on every `results`; `line` is ignored).

- [ ] **Step 3: Implement in `helper/omafindd/ipc.py`**

In `__init__` after `self._previews = {}` add `self._seqs = {}`. In the disconnect cleanup next to `self._jumps.pop(writer, None)` add `self._seqs.pop(writer, None)`.

Replace the results branch in `dispatch`:

```python
        if reply["t"] == "results":
            self._results[writer] = {item["id"]: item for item in reply["items"]}
            # The meaning leg of the same search keeps the preview lines the user already saw.
            if reply.get("seq") is not None and reply.get("seq") == self._seqs.get(writer):
                kept = {key: line for key, line in self._jumps.get(writer, {}).items()
                        if key in self._results[writer]}
                self._jumps[writer] = kept
            else:
                self._jumps.pop(writer, None)
            self._seqs[writer] = reply.get("seq")
```

In `_overlay`, replace the block from `how = message.get("how", "open")` to `opener.launch(...)`:

```python
        how = message.get("how", "open")
        line = message.get("line")
        if how not in ("open", "reveal") or (
            line is not None and (type(line) is not int or line < 1)
        ):
            return {"t": "error", "id": item_id, "for": "open", "code": "bad-request",
                    "reason": "Invalid open arguments"}
        target = dict(item)
        if target.get("kind") not in ("text", "code"):
            line = None
        jump = line if line is not None else self._jumps.get(writer, {}).get(item_id)
        if jump is not None:
            target["loc"] = jump
            if target["kind"] == "code":
                target["open_line"] = jump
        opener.launch(target, how=how)
```

- [ ] **Step 4: Send the line from the overlay**

In `SearchView.qml` `act(how)` replace the send:

```qml
    var message = {t: "open", id: item.id, how: how}
    var line = jumpFor(item)
    if (how === "open" && line != null) message.line = line
    if (pending || !service || !service.send(message)) return
```

- [ ] **Step 5: Document it**

In `docs/ipc.md` replace the `open` row (line 141):

```markdown
| `open` | `id`, `how:"open"\|"reveal"` (default `"open"`), optional `line` (int ≥ 1) | Open text and code at `line`, else at the preview jump, else at the chunk start; other kinds ignore `line`. `how:"reveal"` selects the file with detached `nautilus --select`. Offline and missing files run nothing. A bad `how` or `line` replies `error` with `for:"open"`, `code:"bad-request"`. |
```

and replace "new results clear its remembered preview jumps." (line 153-154) with "a `results` reply with a new `seq` clears its remembered preview jumps; the meaning leg of the same `seq` keeps the jumps of ids it still lists."

Add the example line `{"t":"open","id":"b81e:812","how":"open","line":212}` after the existing `open` example.

- [ ] **Step 6: Run the checks**

Run: `uv run --project helper pytest -q tests/helper/test_ipc_overlay.py && scripts/qmllint.sh`
Expected: PASS; qmllint exit 0.

- [ ] **Step 7: Commit**

```bash
git add helper/omafindd/ipc.py SearchView.qml docs/ipc.md tests/helper/test_ipc_overlay.py
git commit -m "fix(omafindd): open text results at the previewed line"
```

---

### Task 4: Full-resolution previews

**Files:**
- Modify: `helper/omafindd/preview.py:1-25,122-157`, `ui/PreviewLayer.qml:1-5,92-99,381-394`, the video `Image` that shows frames (same `frame` Image), `docs/ipc.md:150,166-167`
- Test: `tests/helper/test_preview.py`

**Interfaces:**
- Produces: `preview.QT_IMAGES` (suffix set Qt decodes), `preview.RENDER_SIDE = 1200`, `preview._cache_key(path, *parts) -> str`, `preview._still(path) -> Path` (cached JPEG). An online image's `preview.image` is the original path when Qt decodes it, else a `magick` still.

- [ ] **Step 1: Write the failing tests**

In `tests/helper/test_preview.py` add:

```python
def test_online_image_previews_the_original(environment):
    path = environment / "photo.png"
    path.write_bytes(b"png")
    reply = preview.render({"id": "image", "kind": "image", "path": str(path),
                            "thumb": "/cached.jpg"})
    assert reply["image"] == str(path)


def test_heic_gets_one_cached_render_at_twice_the_box(environment, monkeypatch):
    path = environment / "photo.HEIC"
    path.write_bytes(b"heic")
    calls = []

    def run(argv):
        calls.append(argv)
        Path(argv[-1]).write_bytes(b"jpeg")

    monkeypatch.setattr(preview, "_run", run)
    item = {"id": "image", "kind": "image", "path": str(path), "thumb": "/cached.jpg"}
    first = preview.render(item)["image"]
    assert preview.render(item)["image"] == first
    assert len(calls) == 1
    assert calls[0][:5] == ["magick", str(path), "-auto-orient", "-resize", "1200x840>"]
    assert first.endswith(".jpg") and Path(first).read_bytes() == b"jpeg"


def test_pdf_page_renders_at_render_side(environment, monkeypatch):
    path = environment / "a.pdf"
    path.write_bytes(b"%PDF")
    calls = []

    def run(argv):
        calls.append(argv)
        Path(argv[-1] + ".png").write_bytes(b"png")

    monkeypatch.setattr(preview, "_run", run)
    preview.render({"id": "pdf", "kind": "pdf", "path": str(path), "loc": 3})
    assert calls[0][calls[0].index("-scale-to") + 1] == "1200"
```

Change `test_image_uses_thumb_even_offline` nothing (offline stays the thumb). In `test_failed_concurrent_render_preserves_finished_image` replace the key line with:

```python
    key = preview._cache_key(path, jump, preview.RENDER_SIDE if kind == "pdf" else 1024)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project helper pytest -q tests/helper/test_preview.py`
Expected: FAIL (image is the thumb, no `_cache_key`, pdf uses 1024).

- [ ] **Step 3: Implement in `helper/omafindd/preview.py`**

After `_run` add:

```python
# Formats Qt's installed image plugins decode; HEIC, AVIF and RAW go through magick.
QT_IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
# Twice the 600 x 420 preview box, so a 2x display still gets a full-size picture.
RENDER_SIDE = 1200


def _cache_key(path, *parts):
    stamp = ":".join(str(part) for part in (path, path.stat().st_mtime_ns, *parts))
    return hashlib.sha256(stamp.encode()).hexdigest()


def _publish(image, argv_for):
    if not image.exists():
        with tempfile.TemporaryDirectory(dir=image.parent) as directory:
            temporary = Path(directory) / image.name
            produced = argv_for(temporary)
            os.replace(produced, image)
    return image


def _still(path):
    image = paths.preview_dir() / (_cache_key(path, "still", RENDER_SIDE) + ".jpg")

    def convert(temporary):
        _run(["magick", str(path), "-auto-orient", "-resize",
              f"{RENDER_SIDE}x{RENDER_SIDE * 7 // 10}>", "-quality", "90", str(temporary)])
        return temporary

    return _publish(image, convert)
```

In `render`, replace the `elif kind == "image":` branch:

```python
    elif kind == "image":
        path = Path(item["path"])
        image = path if path.suffix.lower() in QT_IMAGES else _still(path)
        reply.update(mode="image", image=str(image))
```

Replace the `elif kind in ("pdf", "video"):` branch:

```python
    elif kind in ("pdf", "video"):
        path = Path(item["path"])
        jump = max(1, int(item.get("loc") or 1)) if kind == "pdf" else item.get("loc") or 0
        side = RENDER_SIDE if kind == "pdf" else 1024
        image = paths.preview_dir() / (
            _cache_key(path, jump, side) + (".png" if kind == "pdf" else ".jpg"))

        def draw(temporary):
            if kind == "pdf":
                _run(["pdftoppm", "-f", str(jump), "-l", str(jump), "-scale-to", str(side),
                      "-singlefile", "-png", str(path), str(temporary.with_suffix(""))])
            else:
                _run(["ffmpeg", "-v", "error", "-ss", str(jump), "-i", str(path),
                      "-frames:v", "1", "-vf", f"scale={side}:-2", "-y", str(temporary)])
            return temporary

        _publish(image, draw)
        reply.update(mode="image", jump=jump, image=str(image))
```

`1200 * 7 // 10` is 840, which matches the test's `1200x840>`.

- [ ] **Step 4: Run tests**

Run: `uv run --project helper pytest -q tests/helper/test_preview.py`
Expected: PASS (the real `pdftoppm` test still finds its cached PNG on the second render).

- [ ] **Step 5: Load at the box size in `ui/PreviewLayer.qml`**

Add `import QtQuick.Window` after `import QtQuick`. Replace the `frame` Image (lines 92-99):

```qml
      Image {
        id: frame
        anchors.fill: parent
        source: root.imageSource
        fillMode: Image.PreserveAspectFit
        asynchronous: true
        // Decode at the box size in device pixels, then mipmap so a downscale stays sharp.
        sourceSize: Qt.size(Math.round(width * Screen.devicePixelRatio), Math.round(height * Screen.devicePixelRatio))
        mipmap: true
        smooth: true
        autoTransform: true
        opacity: root.offline ? 0.5 : 1
      }
```

This Image also shows video frames, so they get `mipmap: true` with it.

Replace the PDF box (lines 381-394) size and Image:

```qml
    Rectangle {
      anchors.centerIn: parent
      visible: root.kind === "pdf" && !root.offline
      width: Style.space(600)
      height: Plugin.Tokens.mediaHeight
      radius: Style.cornerRadius
      color: Color.popups.background
      clip: true

      Image {
        anchors.fill: parent
        source: root.kind === "pdf" ? root.imageSource : ""
        fillMode: Image.PreserveAspectFit
        asynchronous: true
        sourceSize: Qt.size(Math.round(width * Screen.devicePixelRatio), Math.round(height * Screen.devicePixelRatio))
        mipmap: true
        smooth: true
      }
```

- [ ] **Step 6: Document it**

In `docs/ipc.md` preview row (line 150) replace "images use their thumbnail or source" with "online images use the source file, or a cached `magick` still at 1200 x 840 when Qt cannot decode the format (HEIC, AVIF, RAW); PDF pages render 1200 px on the long side". In the cache paragraph (lines 166-167) replace "keyed by source path, mtime and page/second" with "keyed by source path, mtime, page/second and render size; image stills live there too".

- [ ] **Step 7: Run the checks**

Run: `scripts/qmllint.sh && uv run --project helper ruff check helper tests bin/omafind scripts`
Expected: exit 0; "All checks passed!".

- [ ] **Step 8: Commit**

```bash
git add helper/omafindd/preview.py ui/PreviewLayer.qml docs/ipc.md tests/helper/test_preview.py
git commit -m "fix(search): preview images and pdf pages at full resolution"
```

### Task 5: Indexing progress popover

**Files:**
- Create: `ui/KindProgress.qml`
- Modify: `helper/omafindd/setup.py:25-34,88-100`, `Service.qml` (add `requestProgress` next to `requestRuntimeStatus`, line 195), `ui/SetupIndex.qml:133-177`, `lib/keys.js`, `SearchView.qml` (properties, `reset`, `handleKey`, footer, new popover), `ui/Footer.qml:9-35,167-195`, `docs/ipc.md` setup table
- Test: `tests/helper/test_ipc_setup.py`, `tests/js/keys.test.mjs`

**Interfaces:**
- Consumes: `KeyMap.action` from Task 2.
- Produces: request `{"t":"index_progress"}` replies the latest `progress` body (same shape as the `index_start` reply), runs nothing.
- Produces: `Service.requestProgress() -> bool`; `KindProgress { progress: var; labelWidth: real; textWidth: real }`; `Footer.progressClicked()` signal; key action `"progress"` for Ctrl+I.

- [ ] **Step 1: Write the failing tests**

Append to `tests/helper/test_ipc_setup.py`:

```python
async def test_index_progress_reads_stores_and_spawns_nothing(service):
    result = await service.handle({"t": "index_progress"})
    assert result["t"] == "progress" and result["running"] is False
    assert result["done"] == 0 and result["queued"] == 0
    assert service.test_calls == []
```

Append to `tests/js/keys.test.mjs`:

```js
test('Ctrl I toggles the progress popover with or without a selection', () => {
  const { action } = load('format.js', 'keys.js');
  const ctrlI = { key: 0x49, modifiers: 0x04000000 };
  assert.equal(action(ctrlI, { query: '', row: null }), 'progress');
  assert.equal(action(ctrlI, { query: 'x', row: { type: 'item', item: fixture('pdf').items[0] } }), 'progress');
  assert.equal(action({ key: 0x49, modifiers: 0 }, { query: '', row: null }), null);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project helper pytest -q tests/helper/test_ipc_setup.py -k index_progress && node --test tests/js/keys.test.mjs`
Expected: FAIL ("Unknown setup request." and `null` instead of `progress`).

- [ ] **Step 3: Implement the request**

In `helper/omafindd/setup.py` add `"index_progress",` to `TYPES`, and in `handle` before `if kind == "discover_start":`:

```python
            if kind == "index_progress":
                return await asyncio.to_thread(self._progress)
```

In `lib/keys.js` add `Key_I: 0x49` to `K` and, right after the `last` line in `action`:

```js
  if (ctrl && key === K.Key_I) return "progress"
```

In `Service.qml` after `requestRuntimeStatus`:

```qml
  function requestProgress() { return send({t: "index_progress"}) }
```

The reply is a `progress` message, which `receive` already stores in `progress`.

- [ ] **Step 4: Run tests**

Run: `uv run --project helper pytest -q tests/helper/test_ipc_setup.py && node --test tests/js/keys.test.mjs`
Expected: PASS (`test_setup_messages_are_ignored_before_hello` now also covers `index_progress`).

- [ ] **Step 5: Move the kind rows into `ui/KindProgress.qml`**

```qml
import QtQuick
import qs.Commons
import ".." as Plugin
import "../lib/setup.js" as Setup

// Per-kind indexing rows: label, bar and "done of total" text. The Index step and the search
// view's progress popover both show it.
Column {
  id: root

  property var progress: null
  property real labelWidth: Style.space(80)
  property real textWidth: Style.space(190)

  spacing: Style.space(8)

  Repeater {
    model: Setup.kindRows(root.progress)

    delegate: Item {
      required property var modelData
      width: root.width
      height: kindLabel.implicitHeight

      Label {
        id: kindLabel
        width: root.labelWidth
        text: modelData.label
        font.pixelSize: Style.font.body
      }

      ProgressBar {
        x: root.labelWidth + Style.space(14)
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width - x - root.textWidth - Style.space(14)
        height: Style.space(6)
        fraction: modelData.fraction
        done: modelData.done
      }

      Label {
        anchors.right: parent.right
        width: root.textWidth
        horizontalAlignment: Text.AlignRight
        text: modelData.text
        color: Plugin.Tokens.dim
        font.pixelSize: Style.font.body
      }
    }
  }
}
```

In `ui/SetupIndex.qml` replace the `Column { ... Repeater { model: Setup.kindRows(root.progress) ... } }` block (lines 133-177) with:

```qml
    KindProgress {
      width: parent.width
      topPadding: Style.space(2)
      progress: root.progress
    }
```

- [ ] **Step 6: Footer click target and always-visible progress**

In `ui/Footer.qml` add under the properties: `signal progressClicked()`. Give the progress `Row` (line 167) `id: progressRow`, and add at the end of the root `Item`:

```qml
  MouseArea {
    x: right.x + progressRow.x
    y: right.y + progressRow.y
    width: progressRow.width
    height: progressRow.height
    visible: progressRow.visible
    cursorShape: Qt.PointingHandCursor
    onClicked: root.progressClicked()
  }
```

- [ ] **Step 7: The popover in `SearchView.qml`**

Add `import "lib/setup.js" as Setup`. Add properties:

```qml
  property bool progressOpen: false
```

and functions:

```qml
  function toggleProgress() {
    progressOpen = !progressOpen
    if (progressOpen && service) service.requestProgress()
  }
```

In `reset()` add `progressOpen = false`. At the top of `handleKey`, before the Ctrl+U branch:

```qml
    // The popover closes before the query clears or the overlay closes.
    if (progressOpen && event.key === Qt.Key_Escape) {
      progressOpen = false
      event.accepted = true
      return
    }
```

and add a case to the switch:

```qml
    case "progress":
      toggleProgress()
      break
```

In the `Parts.Footer` block change `progress` and `hints` and add the click:

```qml
    progress: idleFacts ? idleFacts.progress : null
    hints: root.idle || !root.reply
      ? (idleFacts && idleFacts.progress ? [{keys: ["Ctrl", "I"], label: "progress"}] : []).concat([{keys: ["Esc"], label: "close"}])
      : root.hintsFor(root.selectedRow)
    onProgressClicked: root.toggleProgress()
```

Add the popover after `Parts.Footer`:

```qml
  // Per-kind progress above the footer's progress bar (Ctrl I or a click on it).
  Rectangle {
    id: progressPopover
    readonly property var progress: root.service ? root.service.progress : null
    visible: root.progressOpen
    anchors.right: parent.right
    anchors.rightMargin: Style.space(18)
    anchors.bottom: footer.top
    anchors.bottomMargin: Style.space(6)
    width: Style.space(460)
    height: popoverColumn.implicitHeight + 2 * Style.space(14)
    radius: Style.cornerRadius
    color: Color.popups.background
    border.width: 1
    border.color: Plugin.Tokens.sep

    Column {
      id: popoverColumn
      x: Style.space(14)
      y: Style.space(14)
      width: parent.width - 2 * x
      spacing: Style.space(10)

      Row {
        spacing: Style.space(10)

        Parts.Label {
          text: progressPopover.progress && !progressPopover.progress.running && progressPopover.progress.done > 0
            ? "Indexing finished" : "Indexing"
          color: Color.foreground
          font.pixelSize: Style.font.body
          font.bold: true
        }

        Parts.SetupFacts {
          anchors.baseline: parent.children[0].baseline
          tokens: Setup.indexHead(progressPopover.progress, null).facts
        }
      }

      Parts.KindProgress {
        width: parent.width
        progress: progressPopover.progress
        labelWidth: Style.space(64)
        textWidth: Style.space(170)
      }
    }
  }
```

- [ ] **Step 8: Document it**

In `docs/ipc.md` setup table add the row:

```markdown
| `index_progress` | `progress` | none; reads the stores and returns the latest snapshot without starting a run |
```

and under the `index_start` example add: "`index_progress` replies the same `progress` body and starts nothing, so a view can fill before the next broadcast."

- [ ] **Step 9: Run the checks**

Run: `scripts/qmllint.sh && node --test "tests/js/*.test.mjs" && uv run --project helper pytest -q tests/helper/test_ipc_setup.py tests/helper/test_qml_text.py`
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add helper/omafindd/setup.py Service.qml SearchView.qml ui/KindProgress.qml ui/SetupIndex.qml ui/Footer.qml lib/keys.js docs/ipc.md tests/helper/test_ipc_setup.py tests/js/keys.test.mjs
git commit -m "feat(search): show per-kind indexing progress from the footer"
```

---

### Task 6: Latency, weaker matches and the step 3 title

**Files:**
- Modify: `lib/searchState.js:76-77`, `lib/results.js:44-50`, `lib/keys.js` (weak branch of `action` and `hints`), `lib/setup.js` (add `indexTitle`), `SearchView.qml:158-166,262-264`, `ui/ResultList.qml:19,186-192`, `ui/WeakRow.qml`, `SetupView.qml:149`
- Test: `tests/js/searchState.test.mjs`, `tests/js/results.test.mjs`, `tests/js/keys.test.mjs`, `tests/js/setup.test.mjs`

**Interfaces:**
- Produces: `Results.group(items, {expanded})` always emits `{type:"weak", key:"weak", count, expanded}` before the weak items when there are any; weak items follow it only when `expanded`.
- Produces: key action `"toggle-weak"` replaces `"expand"`; `hints({type:"weak", expanded})` labels Enter "collapse" or "expand".
- Produces: `Setup.indexTitle(progress, failure) -> "Indexing stopped" | "Indexing finished" | "Indexing your files"`.
- Produces: `ResultList.weakToggled(int index)` signal; `WeakRow.expanded` property.

- [ ] **Step 1: Write the failing tests**

In `tests/js/searchState.test.mjs` add:

```js
test('latency shows whole milliseconds', () => {
  const { initial, reduce, status } = search();
  const typed = reduce(initial(), { type: 'typed', query: 'router', now: 100 }).state;
  const reply = freeze({ ...fixture('main'), seq: 1, ms: { total: 17.418 } });
  const done = reduce(freeze(typed), { type: 'reply', reply });
  assert.deepEqual(plain(status(done.state, reply)), { text: '17 ms', spinner: false });
});
```

(`search`, `fixture`, `freeze`, `plain` are already defined at the top of that file.)

In `tests/js/results.test.mjs` replace the body of `weak results fold once at the end or expand without section headers` with:

```js
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
```

In `tests/js/keys.test.mjs`, in `Enter opens items, Ctrl Enter reveals, ...` change `'expand'` to `'toggle-weak'`, and in the hints test from Task 2 replace the weak assertion with:

```js
  assert.deepEqual(plain(hints({ type: 'weak', expanded: false })), [
    { keys: ['Enter'], label: 'expand' }, { keys: ['Esc'], label: 'close' }
  ]);
  assert.deepEqual(plain(hints({ type: 'weak', expanded: true })), [
    { keys: ['Enter'], label: 'collapse' }, { keys: ['Esc'], label: 'close' }
  ]);
```

In `tests/js/setup.test.mjs` add:

```js
test('step 3 title follows the run outcome', () => {
  assert.equal(s.indexTitle(null, ''), 'Indexing your files');
  assert.equal(s.indexTitle({...progress, running: true}, ''), 'Indexing your files');
  assert.equal(s.indexTitle({...progress, running: false, done: 5, queued: 0}, ''), 'Indexing finished');
  assert.equal(s.indexTitle({...progress, running: false, exit: 1}, 'exit 1'), 'Indexing stopped');
  assert.equal(s.indexTitle({...progress, running: true}, 'No folders are selected.'), 'Indexing stopped');
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test tests/js/searchState.test.mjs tests/js/results.test.mjs tests/js/keys.test.mjs tests/js/setup.test.mjs`
Expected: FAIL ("17.418 ms", no weak row when expanded, `expand` label, `indexTitle is not a function`).

- [ ] **Step 3: Implement**

`lib/searchState.js` lines 76-77:

```js
  return {text: (state.phase === "done" || state.phase === "degraded") && result && result.ms
    ? Math.round(result.ms.total) + " ms" : "", spinner: false}
```

`lib/results.js` replace the tail of `group` (lines 44-50):

```js
  if (weak.length) rows.push({type: "weak", key: "weak", count: weak.length, expanded: !!(opts && opts.expanded)})
  if (opts && opts.expanded) {
    for (var w = 0; w < weak.length; w++) {
      rows.push({type: "item", key: weak[w].id, item: weak[w], badge: badge(weak[w]), weak: true})
    }
  }
```

`lib/keys.js`: in `action` the weak line becomes

```js
  if (row.type === "weak") return enter && !ctrl ? "toggle-weak" : null
```

and in `hints`:

```js
  if (row.type === "weak") return [{keys: ["Enter"], label: row.expanded ? "collapse" : "expand"}, close]
```

`lib/setup.js` after `indexFailure`:

```js
// Step 3's title: stopped on a failure, finished once a run ends with files done.
function indexTitle(progress, failure) {
  if (failure) return "Indexing stopped"
  if (progress && !progress.running && progress.done > 0 && !progress.queued) return "Indexing finished"
  return "Indexing your files"
}
```

- [ ] **Step 4: Run tests**

Run: `node --test "tests/js/*.test.mjs"`
Expected: PASS.

- [ ] **Step 5: Wire the fold toggle**

`SearchView.qml`: replace `expand()` (lines 158-166) with:

```qml
  // The fold row stays where it is, so the selection stays on it either way.
  function toggleWeak() {
    expanded = !expanded
    var result = Results.group(reply.items, {expanded: expanded}).rows
    var weakAt = -1
    for (var i = 0; i < result.length; i++) if (result[i].type === "weak") weakAt = i
    rows = result
    selectedIndex = weakAt >= 0 ? weakAt : Results.firstSelection(result)
    userMoved = true
  }
```

In `handleKey` replace `case "expand": expand()` with `case "toggle-weak": toggleWeak()`. On `Parts.ResultList` add `onWeakToggled: index => root.toggleWeak()`.

`ui/ResultList.qml`: add `signal weakToggled(int index)` after `signal picked(int index)`, and on the `WeakRow` delegate:

```qml
          expanded: slot.row && slot.type === "weak" ? !!slot.row.expanded : false
          onClicked: {
            root.picked(slot.rowIndex)
            root.weakToggled(slot.rowIndex)
          }
```

`ui/WeakRow.qml`: add `import "../lib/format.js" as Format`, `property bool expanded: false`, rotate the chevron and count through `Format.count`:

```qml
    Icon {
      anchors.verticalCenter: parent.verticalCenter
      name: "chevron"
      size: Style.space(12)
      strokeWidth: 2
      color: Plugin.Tokens.dim
      rotation: root.expanded ? 180 : 0
      Behavior on rotation { NumberAnimation { duration: 120 } }
    }

    Label {
      anchors.verticalCenter: parent.verticalCenter
      text: Format.count(root.count) + (root.count === 1 ? " weaker match" : " weaker matches")
      color: Plugin.Tokens.dim
    }
```

Update its header comment to "Enter or a click folds and unfolds the weaker hits."

`SetupView.qml` line 149: the step 3 title becomes `Setup.indexTitle(root.service ? root.service.progress : null, root.indexFailure)`:

```qml
          title: root.step === 1 ? "Set up omafind" : root.step === 2 ? "Pick the folders to search"
            : Setup.indexTitle(root.service ? root.service.progress : null, root.indexFailure)
```

- [ ] **Step 6: Run the checks**

Run: `scripts/qmllint.sh && node --test "tests/js/*.test.mjs"`
Expected: exit 0; all pass.

- [ ] **Step 7: Commit**

```bash
git add lib/searchState.js lib/results.js lib/keys.js lib/setup.js SearchView.qml SetupView.qml ui/ResultList.qml ui/WeakRow.qml tests/js
git commit -m "fix(search): round latency and let weaker matches fold again"
```

---

### Task 7: Media-only dataset rule

**Files:**
- Modify: `helper/omafindd/rules.py:80-97,208-245`, `helper/omafindd/reconcile.py:26-28`
- Test: `tests/helper/test_rules.py:74-98,147-156`, `tests/helper/test_leftout.py:91-95`

**Interfaces:**
- Produces: `rules.MEDIA_KINDS = ("image", "video", "audio")`.
- Produces: `rules.datasets(paths, *, root) -> dict[Path, {"kind": str, "files": int, "named": int}]`: a folder (not `root`) with at least 300 files of one media kind, at least 70% of them machine-named; `named` is the rounded percentage. Names only, never `stat`.
- Produces: `rules.keep(paths) -> Iterator[Path | Skip]` with only the size cap; no `root` parameter.
- Produces: `rules.looks_machine_named(stem)` is false for camera prefixes and ISO-date stems.

- [ ] **Step 1: Write the failing tests**

In `tests/helper/test_rules.py` replace `test_dataset_threshold_and_root_exemption` with:

```python
def test_keep_never_drops_a_checked_dataset(tmp_path):
    from omafindd.rules import keep

    folder = tmp_path / "data"
    folder.mkdir()
    paths = []
    for n in range(300):
        path = folder / f"clip_{n:06}.png"
        path.write_bytes(b"png")
        paths.append(path)
    assert list(keep(paths)) == paths


@pytest.mark.parametrize("count,suffix,expected", [
    (300, "png", {"kind": "image", "files": 300, "named": 100}),
    (299, "png", None),
    (300, "txt", None),
    (300, "pdf", None),
    (300, "mp4", {"kind": "video", "files": 300, "named": 100}),
    (300, "flac", {"kind": "audio", "files": 300, "named": 100}),
])
def test_dataset_is_media_only_with_evidence(count, suffix, expected):
    from omafindd.rules import datasets

    paths = [Path(f"/h/data/clip_{n:06}.{suffix}") for n in range(count)]
    found = datasets(paths, root=Path("/h"))
    assert found == ({Path("/h/data"): expected} if expected else {})


def test_dataset_root_is_exempt():
    from omafindd.rules import datasets

    assert datasets([Path(f"/h/clip_{n:06}.png") for n in range(300)], root=Path("/h")) == {}
```

Replace `test_camera_names_are_not_datasets` with:

```python
@pytest.mark.parametrize("stem,machine", [
    ("frame-0042", True), ("3f9a1c0e-abcd", True),
    ("IMG_000123", False), ("DSCN0042", False), ("PXL_20240518_101010", False),
    ("MVIMG_0001", False), ("VID_0042", False), ("GOPR0042", False),
    ("2024-05-18", False), ("2024-05-18_10-10-10", False), ("2024-05-18 101010", False),
    ("invoice", False),
])
def test_camera_and_date_names_are_not_machine_names(stem, machine):
    from omafindd.rules import looks_machine_named

    assert looks_machine_named(stem) is machine
```

In `test_size_cap_is_post_filter`, `test_media_size_caps` replace every `keep([path], root=tmp_path)` with `keep([path])`. In `test_datasets_never_stat` change the last line to:

```python
    assert datasets(paths, root=Path('/h')) == {Path('/h/data'): {'kind': 'image', 'files': 300, 'named': 100}}
```

In `tests/helper/test_leftout.py` line 94 change to `assert set(rules.datasets(...)) == {Path('data')}` (keep the argument list as it is).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project helper pytest -q tests/helper/test_rules.py`
Expected: FAIL (`keep()` needs `root`, `.txt` counts as a dataset, dates look machine-named, `datasets` returns a set).

- [ ] **Step 3: Implement in `helper/omafindd/rules.py`**

After `_CAMERA_PREFIXES` add:

```python
MEDIA_KINDS = ("image", "video", "audio")
# Stems that start with an ISO date are camera and phone exports, not generated data.
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[-_ T.].*)?")
```

Replace `looks_machine_named`, `datasets` and `keep`:

```python
def looks_machine_named(stem: str) -> bool:
    name = stem.lower()
    if name.startswith(_CAMERA_PREFIXES) or _ISO_DATE.fullmatch(name):
        return False
    return bool(
        re.fullmatch(r"[0-9a-f]{8,}([-_][0-9a-f]{4,})*", name)
        or re.fullmatch(r"[a-z]{0,16}[-_. ]?\d{3,}([-_.]\d+)*", name)
    )


def datasets(paths: Iterable[Path | str], *, root: Path) -> dict[Path, dict]:
    """Media folders that look generated: 300+ files of one media kind, 70%+ machine-named.

    Reads names only. `root` itself is never a dataset.
    """
    groups = defaultdict(list)
    root = str(root)
    for path in paths:
        name = str(path)
        parent = os.path.dirname(name) or '.'
        basename = os.path.basename(name)
        kind = classify_name(basename)
        if parent != root and kind in MEDIA_KINDS:
            stem, suffix = os.path.splitext(basename)
            groups[parent, kind].append(basename if suffix == '.' else stem)
    found = {}
    for (folder, kind), stems in groups.items():
        named = sum(map(looks_machine_named, stems))
        if len(stems) >= 300 and named / len(stems) >= 0.7:
            found[Path(folder)] = {"kind": kind, "files": len(stems),
                                   "named": round(100 * named / len(stems))}
    return found


def keep(paths: Iterable[Path]) -> Iterator[Path | Skip]:
    for path in paths:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            continue
        cap = SIZE_CAPS.get(classify(path), 16) * 1024 * 1024
        yield Skip(path, "size-cap") if size > cap else path
```

`"dscn"` and `"dji"` are covered: `"dscn0042".startswith("dsc")` is true and `dji` is already a prefix.

In `helper/omafindd/reconcile.py` line 26-28:

```python
            for candidate in rules.keep(
                rules.walk(root, excludes=setting.get('excludes', []), only=only)
            ):
```

`discovery.scan` still calls `rules.datasets(...)` and iterates, `update`s and tests membership on the result; a dict supports all three, so it keeps working until Task 9 deletes it.

- [ ] **Step 4: Run tests**

Run: `uv run --project helper pytest -q tests/helper/test_rules.py tests/helper/test_leftout.py tests/helper/test_discovery.py tests/helper/test_reconcile.py`
Expected: PASS. If `test_reconcile.py` has a test expecting `Skip(..., "dataset")` or a `skipped["dataset"]` count, change its expectation to the files being indexed, because a checked folder is always indexed now.

- [ ] **Step 5: Run the suite and lint**

Run: `uv run --project helper pytest -q && uv run --project helper ruff check helper tests bin/omafind scripts`
Expected: 834+ passed; ruff clean.

- [ ] **Step 6: Commit**

```bash
git add helper/omafindd/rules.py helper/omafindd/reconcile.py tests/helper/test_rules.py tests/helper/test_leftout.py
git commit -m "fix(omafindd): index checked dataset folders and limit the rule to media"
```

### Task 8: Lazy discovery primitives

**Files:**
- Modify: `helper/omafindd/discovery.py` (add after `xdg_dirs`; rename `_device` to `device` at line 295 and its one caller in `scan`)
- Test: `tests/helper/test_discovery.py`

**Interfaces:**
- Consumes: `rules.walk`, `rules.classify_name`, `rules.reason_name`, `rules.datasets` and `rules.MEDIA_KINDS` from Task 7.
- Produces: `discovery.XDG_PICKS`, `discovery.LIMIT = 500`.
- Produces: `discovery.folders(path) -> list[{"path", "name", "repo": bool, "hasChildren": bool}]`, sorted by name, at most `LIMIT`; raises `OSError` when `path` cannot be read.
- Produces: `discovery.top(*, home, volume=None, run=subprocess.run, lsblk=None, xdg=None, volume_of=None) -> {"roots": [{"path", "volume"}], "folders": [{"path", "name", "repo", "hasChildren", "xdg", "volume"}]}`. Raises `ValueError` for a volume that is not mounted.
- Produces: `class discovery.Walk(root, *, popen=subprocess.Popen, clock=time.monotonic)` with `run(emit, *, every=.25)`, `stop()`, `snapshot() -> dict`, `count(path) -> dict | None`, `dataset(path) -> dict | None`, attributes `root: Path`, `done: bool`, `seconds: float | None`, `error: str | None`. Batches passed to `emit` are `{"root": str, "counts": {abs folder: {text, pdf, image, video, audio}}, "done": bool, "seconds": float | None}`; the last one has `"done": True` and `"datasets": [{"path", "kind", "files", "named"}]`, plus `"error"` when the walk failed.
- Produces: `discovery.children(path, walk=None) -> {"path", "dirs": [{"path", "name", "repo", "hasChildren", "counts": dict | None, "rule": "dataset" | None, "evidence": dict | None}], "error": str | None}`, sorted by indexable files, then name.
- Produces: `discovery.snapshot(*, home, volume=None) -> dict` (the `discover --json` body) and `discovery.device(home) -> "gpu" | "cpu"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/helper/test_discovery.py`:

```python
ZERO = dict.fromkeys(discovery.KINDS, 0)


def test_folders_hide_symlinks_hidden_heavy_and_secrets(tmp_path):
    for name in ("Documents", "code", ".cache", "node_modules", "secrets"):
        (tmp_path / name).mkdir()
    (tmp_path / "code/.git").mkdir()
    (tmp_path / "Documents/tax").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "Documents")
    (tmp_path / "file.txt").write_text("x")
    rows = discovery.folders(tmp_path)
    assert rows == [
        {"path": str(tmp_path / "code"), "name": "code", "repo": True, "hasChildren": False},
        {"path": str(tmp_path / "Documents"), "name": "Documents", "repo": False,
         "hasChildren": True},
    ]


def test_top_reads_one_level_and_marks_xdg_and_volumes(tmp_path):
    home = tmp_path / "home"
    for name in ("Documents", "Pictures", "code"):
        (home / name).mkdir(parents=True)
    drive = tmp_path / "drive"
    drive.mkdir()
    lsblk = {"blockdevices": [{"uuid": "usb", "mountpoints": [str(drive)], "rm": True}]}
    body = discovery.top(home=home, lsblk=lsblk,
                         xdg={"DOCUMENTS": home / "Documents", "TEMPLATES": home / "code"},
                         volume_of=lambda path: ("root", Path("/")))
    rows = {row["name"]: row for row in body["folders"]}
    assert list(rows) == ["code", "Documents", "Pictures", str(drive)]
    assert [name for name, row in rows.items() if row["xdg"]] == ["Documents"]
    assert rows[str(drive)]["volume"] == "usb" and rows["Documents"]["volume"] == "root"
    assert body["roots"] == [{"path": str(home), "volume": "root"},
                             {"path": str(drive), "volume": "usb"}]


def test_top_for_a_volume_lists_the_mount(tmp_path):
    drive = tmp_path / "drive"
    (drive / "Photos").mkdir(parents=True)
    lsblk = {"blockdevices": [{"uuid": "usb", "mountpoints": [str(drive)], "rm": True}]}
    body = discovery.top(home=tmp_path / "home", volume="usb", lsblk=lsblk)
    assert body["roots"] == [{"path": str(drive), "volume": "usb"}]
    assert [(r["name"], r["volume"], r["xdg"]) for r in body["folders"]] == [
        ("Photos", "usb", False)]
    with pytest.raises(ValueError):
        discovery.top(home=tmp_path / "home", volume="gone", lsblk=lsblk)


def test_top_caps_rows_at_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "LIMIT", 3)
    for n in range(5):
        (tmp_path / f"d{n}").mkdir()
    body = discovery.top(home=tmp_path, lsblk={"blockdevices": []}, xdg={},
                         volume_of=lambda path: ("root", Path("/")))
    assert [row["name"] for row in body["folders"]] == ["d0", "d1", "d2"]


def test_walk_rolls_counts_up_in_batches(tmp_path):
    (tmp_path / "a/b").mkdir(parents=True)
    (tmp_path / "a/b/x.md").write_text("x")
    (tmp_path / "a/y.pdf").write_bytes(b"%PDF")
    (tmp_path / "a/b/z.png").write_bytes(b"png")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden/w.md").write_text("w")
    (tmp_path / "a/notes.bin").write_bytes(b"0")
    ticks = iter(range(1000))
    walk = discovery.Walk(tmp_path, clock=lambda: next(ticks))
    batches = []
    walk.run(batches.append, every=1)
    assert [batch["done"] for batch in batches] == [False] * (len(batches) - 1) + [True]
    assert len(batches) >= 2
    final = batches[-1]
    assert final["root"] == str(tmp_path) and final["datasets"] == []
    assert isinstance(final["seconds"], float)
    both = ZERO | {"text": 1, "pdf": 1, "image": 1}
    assert walk.count(str(tmp_path)) == both
    assert walk.count(str(tmp_path / "a")) == both
    assert walk.count(str(tmp_path / "a/b")) == ZERO | {"text": 1, "image": 1}
    assert walk.count(str(tmp_path / ".hidden")) == ZERO
    merged = {}
    for batch in batches:
        merged.update(batch["counts"])
    assert merged[str(tmp_path / "a")] == both


def test_walk_reports_media_datasets(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    for n in range(300):
        (folder / f"clip_{n:06}.png").write_bytes(b"png")
    walk = discovery.Walk(tmp_path)
    batches = []
    walk.run(batches.append)
    evidence = {"kind": "image", "files": 300, "named": 100}
    assert batches[-1]["datasets"] == [{"path": str(folder), **evidence}]
    assert walk.dataset(str(folder)) == evidence


def test_walk_of_a_missing_root_ends_with_error(tmp_path):
    walk = discovery.Walk(tmp_path / "gone")
    batches = []
    walk.run(batches.append)
    assert batches[-1]["done"] is True and batches[-1]["error"]
    assert walk.snapshot()["error"] == batches[-1]["error"]


def test_children_counts_are_null_until_the_walk_reaches_them(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "b/x.md").write_text("x")
    walk = discovery.Walk(tmp_path)
    assert [d["counts"] for d in discovery.children(tmp_path, walk)["dirs"]] == [None, None]
    walk.run(lambda batch: None)
    body = discovery.children(tmp_path, walk)
    assert body["error"] is None
    assert [(d["name"], sum(d["counts"].values())) for d in body["dirs"]] == [("b", 1), ("a", 0)]


def test_children_mark_datasets_with_evidence(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    for n in range(300):
        (folder / f"frame_{n:06}.jpg").write_bytes(b"jpg")
    walk = discovery.Walk(tmp_path)
    walk.run(lambda batch: None)
    row = discovery.children(tmp_path, walk)["dirs"][0]
    assert row["rule"] == "dataset"
    assert row["evidence"] == {"kind": "image", "files": 300, "named": 100}


def test_children_of_unreadable_folder_report_error(tmp_path):
    body = discovery.children(tmp_path / "missing")
    assert body == {"path": str(tmp_path / "missing"), "dirs": [],
                    "error": "No such file or directory"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project helper pytest -q tests/helper/test_discovery.py`
Expected: FAIL with `AttributeError: module 'omafindd.discovery' has no attribute 'folders'` (and `top`, `Walk`, `children`).

- [ ] **Step 3: Implement in `helper/omafindd/discovery.py`**

Add `import threading` to the imports. Rename `def _device(home):` to `def device(home):`. `scan` takes a `device=None` keyword that shadows the module function, so add one line after `device`:

```python
_estimate_device = device
```

and in `scan` change `pool.submit(_device, home)` to `pool.submit(_estimate_device, home)`. Task 9 deletes `scan` and this alias. Then add after `xdg_dirs`:

```python
# The six XDG folders the Folders step checks when it opens.
XDG_PICKS = ("DOCUMENTS", "PICTURES", "VIDEOS", "MUSIC", "DOWNLOAD", "DESKTOP")
LIMIT = 500


def _visible(entry) -> bool:
    try:
        return entry.is_dir(follow_symlinks=False) and rules.reason_name(entry.name) is None
    except OSError:
        return False


def _has_children(path) -> bool:
    try:
        with os.scandir(path) as entries:
            return any(_visible(entry) for entry in entries)
    except OSError:
        return False


def folders(path) -> list[dict]:
    """Child folders of `path` the tree shows, by name. Raises OSError when `path` is unreadable.

    Symlinks, hidden names, heavy and vendor names and secret names are left out.
    """
    rows = []
    with os.scandir(path) as entries:
        for entry in entries:
            if _visible(entry):
                child = Path(entry.path)
                rows.append({"path": str(child), "name": entry.name,
                             "repo": (child / ".git").exists(),
                             "hasChildren": _has_children(child)})
    return sorted(rows, key=lambda row: (row["name"].casefold(), row["name"]))[:LIMIT]


def top(*, home: Path, volume: str | None = None, run=subprocess.run, lsblk=None, xdg=None,
        volume_of=None) -> dict:
    """The first level of the Folders step: one directory read per root.

    Without `volume` the roots are `home` and every mounted non-system volume; volumes outside
    `home` become extra rows. With `volume` the root is that volume's mount.
    """
    home = home.absolute()
    if lsblk is None:
        result = run(['lsblk', '-J', '-o', 'UUID,LABEL,FSTYPE,SIZE,RM,HOTPLUG,MOUNTPOINTS'],
                     capture_output=True, check=True)
        lsblk = json.loads(result.stdout)
    volumes = non_system_volumes(lsblk)
    if volume is not None:
        mount = next((path for uuid, path in volumes if uuid == volume), None)
        if mount is None:
            raise ValueError("That drive is not mounted. Plug it in and try again.")
        rows = [dict(row, xdg=False, volume=volume) for row in folders(mount)]
        return {"roots": [{"path": str(mount), "volume": volume}], "folders": rows}
    xdg = xdg_dirs(home) if xdg is None else xdg
    picks = {str(xdg[name]) for name in XDG_PICKS if name in xdg}
    lookup = _volume_lookup(lsblk) if volume_of is None else volume_of
    rows = [dict(row, xdg=row["path"] in picks) for row in folders(home)]
    roots = [{"path": str(home), "volume": lookup(home)[0]}]
    for uuid, mount in volumes:
        roots.append({"path": str(mount), "volume": uuid})
        if not mount.is_relative_to(home):
            rows.append({"path": str(mount), "name": str(mount),
                         "repo": (mount / ".git").exists(), "hasChildren": True,
                         "xdg": False, "volume": uuid})
    for row in rows:
        row.setdefault("volume", lookup(Path(row["path"]))[0])
    return {"roots": roots, "folders": rows[:LIMIT]}


class Walk:
    """One fd pass over a root that rolls indexable file counts up to every folder above them.

    `run` blocks; the daemon calls it in a thread and reads `count`, `dataset` and `snapshot`
    from the event loop, so shared state sits behind a lock.
    """

    def __init__(self, root, *, popen=subprocess.Popen, clock=time.monotonic):
        self.root = Path(root)
        self.popen, self.clock = popen, clock
        self.counts = {}
        self.datasets = []
        self.done = False
        self.seconds = None
        self.error = None
        self._stop = False
        self._lock = threading.Lock()

    def stop(self):
        self._stop = True

    def count(self, path):
        with self._lock:
            counts = self.counts.get(path)
            if counts is not None:
                return dict(counts)
            return dict.fromkeys(KINDS, 0) if self.done else None

    def dataset(self, path):
        with self._lock:
            found = next((entry for entry in self.datasets if entry["path"] == path), None)
        return None if found is None else {k: v for k, v in found.items() if k != "path"}

    def snapshot(self):
        with self._lock:
            body = {"root": str(self.root),
                    "counts": {path: dict(counts) for path, counts in self.counts.items()},
                    "done": self.done, "seconds": self.seconds}
            if self.done:
                body["datasets"] = list(self.datasets)
            if self.error:
                body["error"] = self.error
        return body

    def _batch(self, changed):
        with self._lock:
            return {"root": str(self.root),
                    "counts": {path: dict(self.counts[path]) for path in changed},
                    "done": self.done, "seconds": self.seconds}

    def run(self, emit, *, every=.25):
        started = last = self.clock()
        root = str(self.root)
        changed, media = set(), []
        listing = None
        try:
            listing = rules.walk(self.root, excludes=[], run=self.popen)
            for path in listing:
                if self._stop:
                    break
                name = str(path)
                kind = rules.classify_name(os.path.basename(name))
                if kind is None:
                    continue
                if kind in rules.MEDIA_KINDS:
                    media.append(name)
                folder = os.path.dirname(name)
                with self._lock:
                    while True:
                        counts = self.counts.setdefault(folder, dict.fromkeys(KINDS, 0))
                        counts[kind] += 1
                        changed.add(folder)
                        if len(folder) <= len(root):
                            break
                        folder = os.path.dirname(folder)
                now = self.clock()
                if now - last >= every:
                    emit(self._batch(changed))
                    changed, last = set(), now
        except OSError as error:
            self.error = str(error) or type(error).__name__
        finally:
            if listing is not None:
                listing.close()
        found = rules.datasets(media, root=self.root)
        with self._lock:
            self.datasets = [{"path": str(path), **evidence}
                             for path, evidence in sorted(found.items())]
            self.done = True
            self.seconds = round(self.clock() - started, 1)
        batch = self._batch(changed)
        batch["datasets"] = list(self.datasets)
        if self.error:
            batch["error"] = self.error
        emit(batch)


def children(path, walk=None) -> dict:
    """One level under `path`. Counts come from `walk`, null until the walk reaches a folder."""
    try:
        rows = folders(path)
    except OSError as error:
        return {"path": str(path), "dirs": [], "error": error.strerror or str(error)}
    for row in rows:
        row["counts"] = walk.count(row["path"]) if walk is not None else None
        row["evidence"] = walk.dataset(row["path"]) if walk is not None else None
        row["rule"] = "dataset" if row["evidence"] else None
    rows.sort(key=lambda row: (-sum((row["counts"] or {}).values()), row["name"].casefold()))
    return {"path": str(path), "dirs": rows, "error": None}


def snapshot(*, home: Path, volume: str | None = None) -> dict:
    """The `discover --json` body: what `discover_start` replies, without walking."""
    return {"home": str(home.absolute()), "device": device(home), "rates": RATES,
            **top(home=home, volume=volume)}
```

`listing.close()` raises `GeneratorExit` inside `rules.walk`'s `with run(...)` block, which closes fd's pipe and reaps it, so a stopped walk leaves no `fd` behind. Popen on a missing `cwd` raises `FileNotFoundError` (an `OSError`) on the first `next()`, which the missing-root test relies on.

- [ ] **Step 4: Run tests**

Run: `uv run --project helper pytest -q tests/helper/test_discovery.py`
Expected: PASS, old and new tests alike.

- [ ] **Step 5: Lint**

Run: `uv run --project helper ruff check helper tests bin/omafind scripts`
Expected: "All checks passed!".

- [ ] **Step 6: Commit**

```bash
git add helper/omafindd/discovery.py tests/helper/test_discovery.py
git commit -m "feat(omafindd): read folders one level at a time and count in one walk"
```

---

### Task 9: Lazy discovery in the daemon

**Files:**
- Modify: `helper/omafindd/setup.py:24-141,250-345,383-400`, `helper/omafindd/discovery.py` (delete the old scan), `bin/omafind:398-425`, `docs/ipc.md:184-262` (setup section, discovery part), `README.md` (the `discover` CLI line if it describes candidates)
- Test: `tests/helper/test_ipc_setup.py`, `tests/helper/test_discovery.py`, `tests/helper/test_cli.py:333-363`

**Interfaces:**
- Consumes: `discovery.top`, `discovery.Walk`, `discovery.children`, `discovery.device`, `discovery.snapshot`, `discovery.RATES` from Task 8.
- Produces: `SetupService(..., top=discovery.top, walk=discovery.Walk, children=discovery.children, estimate_device=discovery.device, volume_of=discovery._volume_of, list_dirs=discovery.list_dirs, ...)`; `discover` and `tree` keywords are gone.
- Produces: `SetupService.TYPES` = `runtime_status, runtime_install, runtime_pause, discover_start, discover_children, fs_list, index_start, index_progress, drive_decision`.
- Produces: `discover_start` reply `{"t":"discover_result","volume","home","device","rates","roots":[{path,volume}],"folders":[{path,name,xdg,repo,hasChildren,volume}]}`.
- Produces: broadcast `{"t":"discover_counts","root","counts":{abs path: counts},"done","seconds"}`, last one with `"datasets"` and, on failure, `"error"`.
- Produces: `discover_children {path}` reply `{"t":"discover_children","path","volume","dirs":[...],"error"}`; `volume` is the UUID of the volume holding `path`, or null when it cannot be resolved, so an added folder can be saved as a root.
- Produces: `SetupService.WALK_TTL = 300.0`, `SetupService._discovery` (set of walk and replay tasks; tests await it).

- [ ] **Step 1: Rewrite the fixture and discovery tests in `tests/helper/test_ipc_setup.py`**

Add `from omafindd import discovery` to the imports. Above the `service` fixture add:

```python
COUNTS = {"text": 3, "pdf": 1, "image": 0, "video": 0, "audio": 0}
ZERO = dict.fromkeys(COUNTS, 0)


class FakeWalk:
    def __init__(self, root):
        self.root = root
        self.done = False
        self.stopped = False

    def run(self, emit, every=.25):
        emit({"root": str(self.root), "counts": {str(self.root / "Documents"): COUNTS},
              "done": False, "seconds": None})
        self.done = True
        emit({"root": str(self.root), "counts": {}, "done": True, "seconds": 0.4,
              "datasets": []})

    def snapshot(self):
        return {"root": str(self.root), "counts": {str(self.root / "Documents"): COUNTS},
                "done": self.done, "seconds": 0.4 if self.done else None}

    def count(self, path):
        if path == str(self.root / "Documents"):
            return COUNTS
        return ZERO if self.done else None

    def dataset(self, path):
        return None

    def stop(self):
        self.stopped = True
```

In the fixture replace the `scan = ...` line and the `tree` function with:

```python
    walks = []

    def top(*, home, volume=None):
        if volume is not None:
            return {"roots": [{"path": "/media/usb", "volume": volume}], "folders": []}
        return {"roots": [{"path": str(home), "volume": "u"}],
                "folders": [{"path": "/h/Documents", "name": "Documents", "xdg": True,
                             "repo": False, "hasChildren": True, "volume": "u"}]}

    def walk(root):
        walks.append(FakeWalk(root))
        return walks[-1]

    def children(path, walk):
        return {"path": path, "error": None,
                "dirs": [{"path": path + "/tax", "name": "tax", "repo": False,
                          "hasChildren": False, "counts": walk.count(path + "/tax"),
                          "rule": None, "evidence": None}]}
```

and in the `SetupService(...)` call replace `discover=lambda **kw: scan, tree=tree,` with:

```python
        top=top,
        walk=walk,
        children=children,
        estimate_device=lambda home: "gpu",
        volume_of=lambda path: ("u", Path("/h")),
```

and add `setup.test_walks = walks` next to the other `test_*` attributes.

Replace `test_discover_start` and `test_discover_tree` with:

```python
async def test_discover_start_replies_one_level_then_streams_counts(service):
    result = await service.handle({"t": "discover_start"})
    assert result == {
        "t": "discover_result", "volume": None, "home": "/h", "device": "gpu",
        "rates": discovery.RATES, "roots": [{"path": "/h", "volume": "u"}],
        "folders": [{"path": "/h/Documents", "name": "Documents", "xdg": True,
                     "repo": False, "hasChildren": True, "volume": "u"}]}
    await asyncio.gather(*service._discovery)
    assert service.test_pushes == [
        {"t": "discover_counts", "root": "/h", "counts": {"/h/Documents": COUNTS},
         "done": False, "seconds": None},
        {"t": "discover_counts", "root": "/h", "counts": {}, "done": True, "seconds": 0.4,
         "datasets": []}]


async def test_repeat_discover_start_reuses_walk_and_replays_counts(service):
    now = [0.0]
    service.clock = lambda: now[0]
    await service.handle({"t": "discover_start"})
    await asyncio.gather(*service._discovery)
    service.test_pushes.clear()
    await service.handle({"t": "discover_start"})
    await asyncio.gather(*service._discovery)
    assert len(service.test_walks) == 1
    assert service.test_pushes == [{"t": "discover_counts", **service.test_walks[0].snapshot()}]
    now[0] = service.WALK_TTL + 1
    await service.handle({"t": "discover_start"})
    await asyncio.gather(*service._discovery)
    assert len(service.test_walks) == 2


async def test_walk_failure_ends_with_done_and_error(service):
    def broken(root):
        walk = FakeWalk(root)

        def run(emit, every=.25):
            raise OSError("fd failed: boom")

        walk.run = run
        return walk

    service.walk = broken
    await service.handle({"t": "discover_start"})
    await asyncio.gather(*service._discovery)
    assert service.test_pushes[-1] == {"t": "discover_counts", "root": "/h", "counts": {},
                                       "done": True, "seconds": None,
                                       "error": "fd failed: boom"}


async def test_discover_children_is_null_until_the_walk_reaches_it(service):
    await service.handle({"t": "discover_start"})
    before = await service.handle({"t": "discover_children", "path": "/h/Documents"})
    assert before["t"] == "discover_children" and before["path"] == "/h/Documents"
    assert before["volume"] == "u"
    assert before["dirs"][0]["counts"] is None
    await asyncio.gather(*service._discovery)
    after = await service.handle({"t": "discover_children", "path": "/h/Documents/"})
    assert after["dirs"][0]["counts"] == ZERO
    assert len(service.test_walks) == 1


async def test_discover_children_outside_every_root_walks_that_folder(service):
    await service.handle({"t": "discover_start"})
    await service.handle({"t": "discover_children", "path": "/srv/archive"})
    assert [walk.root for walk in service.test_walks] == [Path("/h"), Path("/srv/archive")]


async def test_stop_stops_running_walks(service):
    await service.handle({"t": "discover_start"})
    await service.stop()
    assert service.test_walks[0].stopped
```

Delete `test_concurrent_discover_start_shares_one_scan`, `test_cancelled_request_does_not_cancel_shared_scan` and `test_picked_folder_secrets_are_in_progress`.

In `test_errors_carry_for_and_no_seq` replace `service.discover = failed` with `service.top = failed`.

In `test_progress_body_from_stores` delete the `service._scan = SimpleNamespace(...)` statement and change the skipped assertion to `assert result["skipped"] == {"size-cap": 2}`.

In `test_bad_request` replace `{"t": "discover_tree"}` with `{"t": "discover_children"}` and add `{"t": "discover_children", "path": "relative/x"}` to the list.

- [ ] **Step 2: Update the CLI tests in `tests/helper/test_cli.py`**

In `test_discover_json_prints_body_and_exits_0` replace the fake and its patch:

```python
    def snapshot(**kwargs):
        calls.append(kwargs)
        return body

    monkeypatch.setattr(discovery, 'snapshot', snapshot)
```

In `test_discover_failure_exits_1_with_one_stderr_line` rename the fake to `snapshot` and patch `discovery.snapshot`.

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --project helper pytest -q tests/helper/test_ipc_setup.py tests/helper/test_cli.py -k "discover or bad_request or errors_carry or progress_body or stop_stops"`
Expected: FAIL (`SetupService.__init__() got an unexpected keyword argument 'top'`).

- [ ] **Step 4: Switch `helper/omafindd/setup.py`**

`TYPES`:

```python
    TYPES = {
        "runtime_status",
        "runtime_install",
        "runtime_pause",
        "discover_start",
        "discover_children",
        "fs_list",
        "index_start",
        "index_progress",
        "drive_decision",
    }
    # A finished walk answers repeat visits for this long; after it the next visit walks again.
    WALK_TTL = 300.0
```

Constructor keywords: replace `discover=discovery.scan, tree=discovery.tree,` with

```python
        top=discovery.top,
        walk=discovery.Walk,
        children=discovery.children,
        estimate_device=discovery.device,
        volume_of=discovery._volume_of,
```

and the assignments: replace `self.discover, self.tree, self.list_dirs = discover, tree, list_dirs` with

```python
        self.top, self.walk, self.children = top, walk, children
        self.estimate_device, self.volume_of, self.list_dirs = estimate_device, volume_of, list_dirs
```

and replace `self._scan = None` and `self._scans = {}` with

```python
        self._walks = {}
        self._walked = {}
        self._discovery = set()
```

Delete `_discover`. In `handle`, replace the `discover_start` and `("discover_tree", "fs_list")` branches with:

```python
            if kind == "discover_start":
                volume = message.get("volume")
                if volume is not None and (not isinstance(volume, str) or not volume):
                    return self._error(kind, "bad-request", "Invalid discovery volume.")
                body = await asyncio.to_thread(self.top, home=self.home, volume=volume)
                device = await asyncio.to_thread(self.estimate_device, self.home)
                replay = []
                for root in body["roots"]:
                    walk, fresh = self._start_walk(root["path"])
                    if not fresh:
                        replay.append(walk)
                if replay:
                    self._track(self._replay(replay))
                return {"t": "discover_result", "volume": volume, "home": str(self.home),
                        "device": device, "rates": discovery.RATES, **body}
            if kind == "discover_children":
                path = message.get("path")
                if not isinstance(path, str) or not Path(path).is_absolute():
                    return self._error(kind, "bad-request", "Pick an absolute folder path.")
                path = os.path.normpath(path)
                walk = self._walk_for(path) or self._start_walk(path)[0]
                body = await asyncio.to_thread(self.children, path, walk)
                try:
                    volume = (await asyncio.to_thread(self.volume_of, Path(path)))[0]
                except (OSError, ValueError, subprocess.SubprocessError):
                    volume = None
                return {"t": kind, **body, "volume": volume}
            if kind == "fs_list":
                path = message.get("path")
                if (
                    not isinstance(path, str)
                    or not path
                    or not (Path(path).is_absolute() or path == "~" or path.startswith("~/"))
                ):
                    return self._error(kind, "bad-request", "Pick an absolute folder path.")
                body = await asyncio.to_thread(self.list_dirs, path, home=self.home)
                return {"t": kind, **body}
```

Add the walk methods after `handle`:

```python
    def _track(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._discovery.add(task)
        task.add_done_callback(self._discovery.discard)
        return task

    def _walk_for(self, path):
        roots = [root for root in self._walks
                 if path == root or path.startswith(root.rstrip("/") + "/")]
        return self._walks[max(roots, key=len)] if roots else None

    def _start_walk(self, root):
        """The walk of `root`: the running or recent one, else a new one. Returns (walk, fresh)."""
        walk = self._walks.get(root)
        finished = self._walked.get(root)
        if walk is not None and (finished is None or self.clock() - finished < self.WALK_TTL):
            return walk, False
        walk = self.walk(Path(root))
        self._walks[root] = walk
        self._walked.pop(root, None)
        self._track(self._run_walk(root, walk))
        return walk, True

    async def _run_walk(self, root, walk):
        loop = asyncio.get_running_loop()
        batches = asyncio.Queue()

        def emit(batch):
            loop.call_soon_threadsafe(batches.put_nowait, batch)

        def run():
            try:
                walk.run(emit)
            except Exception as error:
                emit({"root": root, "counts": {}, "done": True, "seconds": None,
                      "error": str(error)})

        worker = asyncio.ensure_future(asyncio.to_thread(run))
        try:
            while True:
                batch = await batches.get()
                await self.broadcast({"t": "discover_counts", **batch})
                if batch["done"]:
                    break
        finally:
            self._walked[root] = self.clock()
            await asyncio.gather(worker, return_exceptions=True)

    async def _replay(self, walks):
        for walk in walks:
            await self.broadcast({"t": "discover_counts", **walk.snapshot()})
```

In `_progress` delete the whole `if self._scan is not None:` block (the secrets sum). In `stop()` add at the top:

```python
        for walk in self._walks.values():
            walk.stop()
        for task in list(self._discovery):
            task.cancel()
        await asyncio.gather(*self._discovery, return_exceptions=True)
```

`main.py:434` passes none of the changed keywords, so it needs no edit.

- [ ] **Step 5: Delete the old scan from `helper/omafindd/discovery.py`**

Delete `RootTree`, `Scan`, `estimate`, `candidates`, `_listing`, `_listed`, `_root_tree`, `_repos`, `scan`, `tree` and `_estimate_device`. Remove the now unused imports (`Counter`, `defaultdict`, `ThreadPoolExecutor`, `dataclass`, `cache`, `lru_cache`, `leftout`). Keep `KINDS`, `RATES`, `non_system_volumes`, `xdg_dirs`, the Task 8 functions, `device`, `_volume_of`, `_volume_lookup`, `_expand`, `list_dirs`.

In `tests/helper/test_discovery.py` delete the `counts` helper and these tests: `test_25_file_directory_is_proposed_19_is_not`, `test_dense_subtree_at_59_percent_stops_below_parent`, `test_home_and_volume_root_are_never_proposed`, `test_xdg_dirs_with_content_are_checked_others_unchecked`, `test_walk_is_one_fd_listing_per_volume_and_never_stats`, `test_repositories_are_found_by_git_and_count_tracked_files`, `test_scan_body_shape_and_ledger_invariant`, `test_tree_dirs_carry_own_and_subtree_counts`, `test_volume_filter_scans_only_requested_volume`, `test_dataset_names_stay_out_of_found_tree_and_generated_entries`, `test_tree_scans_and_caches_uncovered_root`, `test_picked_root_obeys_global_rules`, `test_broken_repository_does_not_abort_scan`, `test_scan_shares_all_file_listing_and_preserves_hidden_secrets`, `test_shared_listing_does_not_duplicate_nested_xdg_or_volume_files`, `test_repository_counts_keep_the_authoritative_code_classifier`, `test_scan_ancestor_caches_handle_deep_directories`, `test_volume_scan_candidates_are_checked_and_mount_is_echoed`, `test_not_proposed_datasets_include_absolute_path_and_evidence`. Keep `test_explain_counts_dot_heavy_secrets_by_name` (Task 13 removes it), `test_non_system_volumes_from_lsblk`, both `list_dirs` tests, `test_xdg_dirs_reads_home_and_omits_home_itself`, `test_volume_lookup_reuses_mount_table_and_prefers_inner_mount` and the Task 8 tests. Drop imports ruff reports unused (`io`, `subprocess`, `make_documents`).

- [ ] **Step 6: Point the CLI at the snapshot**

In `bin/omafind` `discover()`:

```python
    from omafindd.discovery import snapshot

    try:
        body = snapshot(home=Path(env["HOME"]), volume=parsed.volume)
```

- [ ] **Step 7: Rewrite the discovery part of `docs/ipc.md`**

In the setup table replace the `discover_tree` row with:

```markdown
| `discover_children` | `discover_children` | `path` absolute folder |
| (broadcast) | `discover_counts` | sent while a walk runs |
```

Replace everything from the `discover_start` code block through the end of the `discover_tree` bullets (the block that starts "plugin: {"t":"discover_start"}" and ends before the `fs_list` block) with:

````markdown
```
plugin: {"t":"discover_start"}                      // $HOME plus every non-system volume
plugin: {"t":"discover_start","volume":"<uuid>"}    // one volume only (#6 new-drive flow)
daemon: {"t":"discover_result","volume":null,"home":"/home/u","device":"gpu",
         "rates":{"gpu":{"text":0.07,"pdf":0.37,"image":0.14,"video":3.2,"audio":1.5,"code":0.042},
                  "cpu":{"text":0.13,"pdf":0.54,"image":1.36,"video":18.0,"audio":11.1,"code":0.084},
                  "bytes":{"text":11000,"pdf":48000,"image":7000,"video":40000,"audio":12000,"code":10000}},
         "roots":[{"path":"/home/u","volume":"<uuid>"},{"path":"/run/media/u/USB","volume":"<uuid>"}],
         "folders":[{"path":"/home/u/Documents","name":"Documents","xdg":true,"repo":false,"hasChildren":true,"volume":"<uuid>"},
                    {"path":"/home/u/omaone","name":"omaone","xdg":false,"repo":true,"hasChildren":true,"volume":"<uuid>"},
                    {"path":"/run/media/u/USB","name":"/run/media/u/USB","xdg":false,"repo":false,"hasChildren":true,"volume":"<uuid>"}]}
```
- The reply comes after one directory read per root (plus one peek per folder for `hasChildren`). `folders` lists the folders directly under `$HOME`, sorted by name, then one row per volume mounted outside `$HOME`; with `volume` it lists the folders under that volume's mount. At most 500 rows.
- Symlinks, hidden names, the heavy and vendor names in `rules.HEAVY_GLOBS` and secret names are never listed. `xdg` is true for the Documents, Pictures, Videos, Music, Download and Desktop folders of `user-dirs.dirs`. `repo` is true when the folder holds `.git`.
- `rates` lets the client estimate index size and time for any counts on `device`.
- After the reply the daemon walks each root once with `fd` (one pass over the indexable kinds, no hidden paths, heavy names or secrets) and broadcasts `discover_counts`. A walk of the same root that is running, or finished less than 300 s ago, is reused: the daemon broadcasts its counts so far as one `discover_counts` instead of walking again. Walks stop when the daemon stops.

```
daemon: {"t":"discover_counts","root":"/home/u","done":false,"seconds":null,
         "counts":{"/home/u/Documents":{"text":745,"pdf":67,"image":26,"video":0,"audio":0}}}
daemon: {"t":"discover_counts","root":"/home/u","done":true,"seconds":1.4,"counts":{...},
         "datasets":[{"path":"/home/u/Pictures/frames","kind":"image","files":1418,"named":96}]}
```
- Sent about every 250 ms with the folders whose counts changed since the last batch. `counts` are rolled up: a folder counts every indexable file below it. A folder the walk never reached has no entry; once `done` is true a missing folder has zero files.
- The last batch has `done:true`, `seconds` rounded to 0.1, and `datasets`: media folders with 300 or more files of one kind (image, video or audio) of which at least 70% are machine-named; `named` is that share in percent. A failed walk still ends with `done:true` and adds `error` (a sentence from fd or the OS).

```
plugin: {"t":"discover_children","path":"/home/u/Pictures"}
daemon: {"t":"discover_children","path":"/home/u/Pictures","volume":"<uuid>","error":null,
         "dirs":[{"path":"/home/u/Pictures/frames","name":"frames","repo":false,"hasChildren":false,
                  "counts":{"text":0,"pdf":0,"image":1418,"video":0,"audio":0},
                  "rule":"dataset","evidence":{"kind":"image","files":1418,"named":96}},
                 {"path":"/home/u/Pictures/2024","name":"2024","repo":false,"hasChildren":true,
                  "counts":null,"rule":null,"evidence":null}]}
```
- One level, same filters as `folders`, sorted by indexable files (descending), then by name. `counts` is null until the walk reaches the folder; the counts arrive later in `discover_counts`. A path outside every walked root starts a walk of that path. `volume` is the UUID of the volume holding `path`, or null. An unreadable folder replies `dirs:[]` with `error` set to the OS reason.
````

In the `index_start` bullets replace the example's `"skipped":{"secrets":4,"size-cap":2}` with `"skipped":{"size-cap":2}`, and add after "`skipped` and `failed` omit zero keys.": "Secrets are never listed, so they are not counted in `skipped`."

In the README, if the `omafind discover --json` line describes candidates or a scan, change it to "prints the first level of the Folders step (roots and folders) as JSON".

- [ ] **Step 8: Run tests**

Run: `uv run --project helper pytest -q`
Expected: PASS (count drops by the deleted tests).

- [ ] **Step 9: Lint**

Run: `uv run --project helper ruff check helper tests bin/omafind scripts`
Expected: "All checks passed!".

- [ ] **Step 10: Commit**

```bash
git add helper/omafindd/setup.py helper/omafindd/discovery.py bin/omafind docs/ipc.md README.md tests/helper
git commit -m "feat(omafindd): stream folder counts and answer one level at a time"
```

### Task 10: Selection model in `lib/tree.js`

**Files:**
- Create: `lib/ledgerTree.js` (a verbatim copy of today's `lib/tree.js`, deleted in Task 13), `tests/js/ledgerTree.test.mjs` (today's `tests/js/tree.test.mjs` with `load('ledgerTree.js')`)
- Modify: `lib/tree.js` (rewrite), `ui/SetupFolders.qml:7`, `ui/SetupLeaveOut.qml:6`, `ui/DriveDialog.qml:6`
- Test: `tests/js/tree.test.mjs` (rewrite)

**Interfaces:**
- Produces (`lib/tree.js`, all paths absolute, state objects never mutated):
  - `initial(folders) -> {chosen: string[], skipped: string[], code: string[]}`: folders with `xdg: true` start chosen.
  - `searched(path, state) -> bool`: the nearest ancestor-or-self in `chosen` or `skipped` decides; none means not searched.
  - `mark(path, state) -> "on" | "off" | "mixed"`: mixed when any choice strictly below `path` differs from `path`'s own state.
  - `click(state, path) -> state`: a mixed folder becomes searched whole, otherwise it flips; every choice below `path` is cleared.
  - `toggleCode(state, path) -> state`.
  - `addDatasets(state, datasets: [{path}], proposed: string[]) -> state`: skips each dataset under a searched folder that has no choice of its own and was not proposed before.
  - `value(path, state, countOf) -> counts | null`: searched files under `path` per kind; `countOf(path)` returns rolled-up counts or null; null while any needed count is missing.
  - `isInside(path, folder)`, `parent(path)`, `toRoots(chosen, skipped, volumeOf)` keep their current behavior.
- Produces: `lib/ledgerTree.js` with the old API, imported as `Tree` by the three old QML files until Task 13.

- [ ] **Step 1: Keep the old model under a new name**

```bash
cp lib/tree.js lib/ledgerTree.js
git mv tests/js/tree.test.mjs tests/js/ledgerTree.test.mjs
sed -i "s/load('tree.js')/load('ledgerTree.js')/" tests/js/ledgerTree.test.mjs
sed -i 's#"../lib/tree.js" as Tree#"../lib/ledgerTree.js" as Tree#' ui/SetupFolders.qml ui/SetupLeaveOut.qml ui/DriveDialog.qml
node --test tests/js/ledgerTree.test.mjs
```

Expected: the old tree tests pass against `ledgerTree.js`.

- [ ] **Step 2: Write the failing tests**

`tests/js/tree.test.mjs`:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { load } from './load.mjs';
import { plain, freeze } from './fixtures.mjs';
const t = load('tree.js');
const state = (chosen, skipped = [], code = []) => freeze({ chosen, skipped, code });
const ZERO = { text: 0, pdf: 0, image: 0, video: 0, audio: 0 };
const c = (text, image = 0) => ({ ...ZERO, text, image });

test('the nearest choice decides whether a folder is searched', () => {
  const s = state(['/h/Docs', '/h/Docs/a/b'], ['/h/Docs/a']);
  assert.equal(t.searched('/h/Docs/x', s), true);
  assert.equal(t.searched('/h/Docs/a/c', s), false);
  assert.equal(t.searched('/h/Docs/a/b/deep', s), true);
  assert.equal(t.searched('/h/Pictures', s), false);
  assert.equal(t.searched('/h/Docsx', s), false);
});

test('marks compare choices at any depth below a folder', () => {
  const s = state(['/h/Docs'], ['/h/Docs/a/b/c']);
  assert.equal(t.mark('/h/Docs', s), 'mixed');
  assert.equal(t.mark('/h/Docs/a', s), 'mixed');
  assert.equal(t.mark('/h/Docs/a/b/c', s), 'off');
  assert.equal(t.mark('/h/Docs/z', s), 'on');
  assert.equal(t.mark('/h/Docs/new/child', state(['/h/Docs'])), 'on');
  assert.equal(t.mark('/h', s), 'mixed');
  assert.equal(t.mark('/h/Pictures', s), 'off');
});

test('a click sets the folder and clears every choice below it', () => {
  const s = state(['/h/Docs', '/h/Docs/a/b'], ['/h/Docs/a', '/h/Docs/x']);
  const whole = t.click(s, '/h/Docs');
  assert.deepEqual(plain(whole), { chosen: ['/h/Docs'], skipped: [], code: [] });
  assert.deepEqual(plain(t.click(whole, '/h/Docs')), { chosen: [], skipped: [], code: [] });
  const child = t.click(state(['/h/Docs']), '/h/Docs/a');
  assert.deepEqual(plain(child), { chosen: ['/h/Docs'], skipped: ['/h/Docs/a'], code: [] });
  assert.deepEqual(plain(t.click(child, '/h/Docs/a')), { chosen: ['/h/Docs'], skipped: [], code: [] });
  assert.deepEqual(plain(t.click(state([], ['/h/Docs/a']), '/h/Docs/a/b')),
    { chosen: ['/h/Docs/a/b'], skipped: ['/h/Docs/a'], code: [] });
});

test('XDG folders start chosen and datasets start skipped under a searched parent', () => {
  const s = t.initial(freeze([{ path: '/h/Docs', xdg: true }, { path: '/h/code', xdg: false }]));
  assert.deepEqual(plain(s), { chosen: ['/h/Docs'], skipped: [], code: [] });
  const next = t.addDatasets(s, freeze([{ path: '/h/Docs/frames' }, { path: '/h/code/frames' },
    { path: '/h/Docs/kept' }]), ['/h/Docs/kept']);
  assert.deepEqual(plain(next.skipped), ['/h/Docs/frames']);
  assert.equal(t.mark('/h/Docs', next), 'mixed');
  const chosenSet = t.click(next, '/h/Docs/frames');
  assert.deepEqual(plain(t.addDatasets(chosenSet, [{ path: '/h/Docs/frames' }], ['/h/Docs/frames']).skipped), []);
});

test('value counts searched files from rolled-up counts and waits for missing ones', () => {
  const counts = { '/h/Docs': c(10, 5), '/h/Docs/a': c(4, 5), '/h/Docs/a/b': c(1, 0) };
  const countOf = path => counts[path] || null;
  const s = state(['/h/Docs', '/h/Docs/a/b'], ['/h/Docs/a']);
  assert.deepEqual(plain(t.value('/h/Docs', s, countOf)), c(7, 0));
  assert.deepEqual(plain(t.value('/h/Docs/a', s, countOf)), c(1, 0));
  assert.deepEqual(plain(t.value('/h/Pictures', s, () => c(3))), ZERO);
  assert.equal(t.value('/h/Docs', s, path => path === '/h/Docs/a/b' ? null : counts[path]), null);
  assert.equal(t.value('/h/Docs', state(['/h/Docs']), () => null), null);
});

test('the code toggle keeps its own set through clicks', () => {
  const s = t.toggleCode(state(['/h/Docs']), '/h/omaone');
  assert.deepEqual(plain(s.code), ['/h/omaone']);
  assert.deepEqual(plain(t.toggleCode(s, '/h/omaone').code), []);
  assert.deepEqual(plain(t.click(s, '/h/omaone').code), ['/h/omaone']);
});

test('toRoots turns the sets into roots with relative excludes', () => {
  const s = state(['/h/Docs', '/h/Docs/a/b'], ['/h/Docs/a']);
  assert.deepEqual(plain(t.toRoots(s.chosen, s.skipped, () => 'u')), [
    { path: '/h/Docs', volume: 'u', excludes: ['a'] },
    { path: '/h/Docs/a/b', volume: 'u', excludes: [] }]);
  assert.deepEqual(plain(t.toRoots(['/', '/a'], ['/b'], () => 'v')),
    [{ path: '/', volume: 'v', excludes: ['b'] }]);
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `node --test tests/js/tree.test.mjs`
Expected: FAIL (`t.click is not a function`, old `searched` signature).

- [ ] **Step 4: Rewrite `lib/tree.js`**

```js
.pragma library

// The Folders step selection: absolute paths in `chosen` and `skipped`, and repo folders whose
// code is indexed in `code`. The nearest choice at or above a folder decides it.
var KINDS = ["text", "pdf", "image", "video", "audio"]

function isInside(path, folder) {
  return folder === "" || path === folder || path.indexOf(folder.replace(/\/$/, "") + "/") === 0
}

function parent(path) {
  var index = path.lastIndexOf("/")
  return index < 0 ? "" : path.slice(0, index)
}

function make(chosen, skipped, code) {
  return {chosen: chosen, skipped: skipped, code: code}
}

function initial(folders) {
  return make(folders.filter(function(folder) { return folder.xdg }).map(function(folder) { return folder.path }), [], [])
}

// The choice that decides `path`: {path, on}, or {path: null, on: false} with none above it.
function owner(path, state) {
  var best = {path: null, on: false}
  function consider(list, on) {
    list.forEach(function(folder) {
      if (isInside(path, folder) && (best.path === null || folder.length > best.path.length)) best = {path: folder, on: on}
    })
  }
  consider(state.chosen, true)
  consider(state.skipped, false)
  return best
}

function searched(path, state) {
  return owner(path, state).on
}

function mark(path, state) {
  var on = searched(path, state)
  var differs = (on ? state.skipped : state.chosen).some(function(folder) {
    return folder !== path && isInside(folder, path)
  })
  return differs ? "mixed" : on ? "on" : "off"
}

function click(state, path) {
  var on = mark(path, state) === "mixed" || !searched(path, state)
  function outside(folder) { return !isInside(folder, path) }
  var next = make(state.chosen.filter(outside), state.skipped.filter(outside), state.code)
  if (searched(path, next) !== on) (on ? next.chosen : next.skipped).push(path)
  return next
}

function toggleCode(state, path) {
  var code = state.code.indexOf(path) >= 0
    ? state.code.filter(function(folder) { return folder !== path }) : state.code.concat([path])
  return make(state.chosen, state.skipped, code)
}

// A dataset under a searched folder starts left out. `proposed` lists datasets already offered,
// so one the user checked is not skipped again when a later walk reports it.
function addDatasets(state, datasets, proposed) {
  var skipped = state.skipped.slice()
  datasets.forEach(function(dataset) {
    if (proposed.indexOf(dataset.path) >= 0) return
    var decided = owner(dataset.path, state)
    if (decided.on && decided.path !== dataset.path) skipped.push(dataset.path)
  })
  return make(state.chosen, skipped, state.code)
}

// Choices strictly below `path` with no other choice between them and `path`.
function innermost(path, state) {
  var below = state.chosen.concat(state.skipped).filter(function(folder) {
    return folder !== path && isInside(folder, path)
  })
  return below.filter(function(folder) {
    return !below.some(function(other) { return other !== folder && isInside(folder, other) })
  })
}

// Searched files under `path` per kind. Outside the innermost choices everything follows
// `path`'s own state, so each choice swaps its subtree's share for its own value.
function value(path, state, countOf) {
  var counts = countOf(path)
  if (!counts) return null
  var on = searched(path, state)
  var result = {}
  KINDS.forEach(function(kind) { result[kind] = on ? counts[kind] || 0 : 0 })
  var inner = innermost(path, state)
  for (var i = 0; i < inner.length; i++) {
    var sub = countOf(inner[i])
    var kept = value(inner[i], state, countOf)
    if (!sub || !kept) return null
    KINDS.forEach(function(kind) { result[kind] += kept[kind] - (on ? sub[kind] || 0 : 0) })
  }
  return result
}

function toRoots(chosen, skipped, volumeOf) {
  var folders = chosen.filter(function(path, index) {
    if (chosen.indexOf(path) !== index) return false
    var outer = chosen.filter(function(folder) { return folder !== path && isInside(path, folder) })
    return !outer.some(function(folder) {
      return !skipped.some(function(skip) { return isInside(path, skip) && isInside(skip, folder) && skip !== folder })
    })
  })
  return folders.map(function(path) {
    return {path: path, volume: volumeOf(path), excludes: skipped.filter(function(skip, index) {
      return skip !== path && isInside(skip, path) && skipped.indexOf(skip) === index
    }).map(function(skip) { return skip.slice(path === "/" ? 1 : path.replace(/\/$/, "").length + 1) })}
  })
}
```

- [ ] **Step 5: Run tests**

Run: `node --test "tests/js/*.test.mjs" && scripts/qmllint.sh`
Expected: PASS; qmllint exit 0.

- [ ] **Step 6: Commit**

```bash
git add lib/tree.js lib/ledgerTree.js tests/js/tree.test.mjs tests/js/ledgerTree.test.mjs ui/SetupFolders.qml ui/SetupLeaveOut.qml ui/DriveDialog.qml
git commit -m "refactor(setup): keep folder choices as chosen and skipped paths"
```

---

### Task 11: Discovery caches in `Service.qml`

**Files:**
- Modify: `Service.qml:35-41,77,197-204,338-354,379-391`
- Test: `scripts/qmllint.sh` (the logic lives in QML handlers; Task 12's host check and Task 17 exercise it)

**Interfaces:**
- Consumes: `discover_result`, `discover_counts`, `discover_children` from Task 9.
- Produces on `Service`:
  - `discoverCounts: var` (abs path to counts), `walks: var` (root to `{done, seconds, error}`), `datasets: var` (abs path to `{path, kind, files, named}`), `children: var` (abs path to `{dirs, volume, error}` from its `discover_children` reply).
  - `requestChildren(path) -> bool`: sends `discover_children` once per path until it is answered or fails.
  - `signal childrenReceived(string path)`.
  - `scan()` and `scanDrive(uuid)` keep their names and messages.
- Removes: `trees`, `requestTree`, `treeReceived`, the `discover_tree` case.

- [ ] **Step 1: Replace the tree cache**

Replace `property var trees: ({})` and its comment (lines 38-39) with:

```qml
  // Absolute folder -> rolled-up counts, merged from every discover_counts batch.
  property var discoverCounts: ({})
  // Walk root -> {done, seconds, error} from its latest batch.
  property var walks: ({})
  // Dataset folder -> {path, kind, files, named} from each walk's last batch.
  property var datasets: ({})
  // Folder -> {dirs, volume, error} from discover_children. `childrenAsked` stops a second request.
  property var children: ({})
  property var childrenAsked: ({})
```

Replace `signal treeReceived(var reply)` with `signal childrenReceived(string path)`. Replace `function requestTree(root) { ... }` with:

```qml
  function requestChildren(path) {
    if (children[path] || childrenAsked[path]) return true
    var asked = Object.assign({}, childrenAsked)
    asked[path] = true
    childrenAsked = asked
    return send({t: "discover_children", path: path})
  }
```

- [ ] **Step 2: Handle the new messages**

In `receive`, replace the `case "discover_tree":` block with:

```qml
    case "discover_counts":
      receiveCounts(message)
      break
    case "discover_children":
      var nextChildren = Object.assign({}, children)
      nextChildren[message.path] = {dirs: Array.isArray(message.dirs) ? message.dirs : [],
        volume: typeof message.volume === "string" ? message.volume : "",
        error: typeof message.error === "string" ? message.error : ""}
      children = nextChildren
      childrenReceived(message.path)
      break
```

Add after `receiveSetupError`:

```qml
  function receiveCounts(message) {
    if (typeof message.root !== "string" || !message.counts) return
    var counts = Object.assign({}, discoverCounts)
    for (var path in message.counts) counts[path] = message.counts[path]
    discoverCounts = counts
    var nextWalks = Object.assign({}, walks)
    nextWalks[message.root] = {done: !!message.done, seconds: typeof message.seconds === "number" ? message.seconds : null,
      error: typeof message.error === "string" ? message.error : ""}
    walks = nextWalks
    if (Array.isArray(message.datasets)) {
      var nextSets = Object.assign({}, datasets)
      message.datasets.forEach(entry => nextSets[entry.path] = entry)
      datasets = nextSets
    }
  }
```

In `receiveSetupError`, before `setupFailed(...)`, let a failed children request be retried:

```qml
    if (message.for === "discover_children") childrenAsked = {}
```

- [ ] **Step 3: Lint**

Run: `scripts/qmllint.sh`
Expected: exit 0. `ui/SetupFolders.qml`, `ui/DriveDialog.qml` and `ui/SetupLeaveOut.qml` still call `service.requestTree` and read `service.trees`; qmllint does not resolve those dynamic members, and Tasks 12 and 13 replace those files.

- [ ] **Step 4: Commit**

```bash
git add Service.qml
git commit -m "feat(setup): cache streamed folder counts and children in the service"
```

### Task 12: The lazy Folders step

**Files:**
- Create: `ui/FolderTree.qml`
- Modify: `ui/SetupFolders.qml` (rewrite), `SetupView.qml` (drop the tree sub-view), `ui/FolderRow.qml` (pending spinner, `code` action), `ui/RuleTag.qml:12-22` (dataset and repo tones), `lib/setup.js` (replace `scanFacts`, `scanningFacts`, `rowFacts`, `repoFacts`, `notProposed`; add `walkError`, `datasetFacts`; simplify `panelSize`)
- Test: `tests/js/setup.test.mjs`

**Interfaces:**
- Consumes: `Tree.initial`, `Tree.mark`, `Tree.click`, `Tree.toggleCode`, `Tree.addDatasets`, `Tree.value`, `Tree.toRoots`, `Tree.isInside`, `Tree.searched` (Task 10); `Service.discoverCounts`, `walks`, `datasets`, `children`, `requestChildren`, `childrenReceived` (Task 11); `discover_result.roots/folders` (Task 9).
- Produces: `Setup.scanFacts(folderCount, walks) -> tokens`, `Setup.walkError(walks) -> string`, `Setup.datasetFacts({kind, files, named}) -> tokens`, `Setup.panelSize(step) -> {width, height}`.
- Produces: `FolderTree { service; table; folders; choices; home; rates; device; mount; locked; signal choicesEdited(var choices); readonly totals: {files, bytes, seconds}; readonly count: int; function focusFirst() }`. Task 13's drive dialog uses the same component.
- Produces: `FolderRow.pending: bool` (spinner in the Index cell), `FolderRow.action: "code"` (code toggle, accent when `actionActive`).

- [ ] **Step 1: Write the failing tests**

In `tests/js/setup.test.mjs` replace the tests `chips and panel sizes follow each step`, `scan and not-proposed facts omit zero groups` and `home row facts match the board ledger` with:

```js
test('chips and panel sizes follow each step', () => {
  assert.deepEqual(plain(s.chips(2)), [{label:'Search engine',state:'done',mark:'✓'}, {label:'Folders',state:'cur',mark:'2'}, {label:'Index',state:'todo',mark:'3'}]);
  assert.equal(s.stepLabel(2), 'Step 2 of 3');
  for (const [step, size] of [[1,[760,474]], [2,[1120,992]], [3,[920,574]]]) {
    assert.deepEqual(Object.values(plain(s.panelSize(step))), size);
  }
});
test('scan facts count folders while walks run, then show the walk time', () => {
  assert.deepEqual(values(s.scanFacts(1234, {})), [['folders','1,234'],['scanning','']]);
  assert.deepEqual(values(s.scanFacts(12, {'/h': {done: true, seconds: 1.4}, '/m': {done: false}})), [['folders','12'],['scanning','']]);
  assert.deepEqual(values(s.scanFacts(12, {'/h': {done: true, seconds: 1.44}, '/m': {done: true, seconds: 0.3}})), [['scanned in','1.4 s']]);
  assert.equal(s.walkError({'/h': {done: true, error: ''}}), '');
  assert.equal(s.walkError({'/h': {done: true, error: 'fd failed: boom'}}), 'fd failed: boom');
});
test('dataset facts name the kind, the file count and the machine-named share', () => {
  assert.deepEqual(values(s.datasetFacts({kind: 'image', files: 1418, named: 96})), [['images','1,418'],['named','96%']]);
  assert.deepEqual(values(s.datasetFacts({kind: 'audio', files: 300, named: 70})), [['audio','300'],['named','70%']]);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test tests/js/setup.test.mjs`
Expected: FAIL (`walkError is not a function`, old `scanFacts` reads `body.scan`).

- [ ] **Step 3: Implement the helpers in `lib/setup.js`**

Delete `scanFacts`, `scanningFacts`, `rowFacts`, `repoFacts` and `notProposed`. Add after `KIND_LABELS`:

```js
var DATASET_KINDS = {image: "images", video: "videos", audio: "audio"}
```

and after `engineHint`:

```js
// Folders step header: the folder count while any walk runs, then the slowest walk's time.
function scanFacts(folders, walks) {
  var list = Object.keys(walks || {}).map(function(root) { return walks[root] })
  if (!list.length || list.some(function(walk) { return !walk.done })) {
    return [token("folders", count(folders)), token("scanning", "")]
  }
  var seconds = Math.max.apply(null, list.map(function(walk) { return walk.seconds || 0 }))
  return [token("scanned in", seconds.toFixed(1) + " s")]
}

function walkError(walks) {
  for (var root in walks || {}) if (walks[root].error) return walks[root].error
  return ""
}

function datasetFacts(evidence) {
  return [token(DATASET_KINDS[evidence.kind] || evidence.kind, count(evidence.files)),
    token("named", evidence.named + "%")]
}
```

Replace `panelSize`:

```js
function panelSize(current) {
  if (current === 1) return {width: 760, height: 474}
  if (current === 3) return {width: 920, height: 574}
  return {width: 1120, height: 992}
}
```

Run: `node --test tests/js/setup.test.mjs`
Expected: PASS.

- [ ] **Step 4: Teach `FolderRow` and `RuleTag` the new row parts**

In `ui/FolderRow.qml` add under `property string timeText: ""`:

```qml
  // Counts not known yet: a spinner in the Index cell instead of the estimate.
  property bool pending: false
```

Change the Index cell `Label` (`x: root.table.cellX(7)`) to `visible: !root.hatched && !root.pending && !!root.table`, and add after it:

```qml
    Spinner {
      visible: root.pending && !!root.table
      running: visible
      x: root.table ? root.table.cellX(7) + root.table.widths[7] - width : 0
      anchors.verticalCenter: parent.verticalCenter
    }
```

Change the action column comment to `// Action column: "", "filter", "x", "code" or "lock".`, the action `Rectangle`'s `visible` to `root.action === "filter" || root.action === "x" || root.action === "code"`, and its `Icon` name to `root.action === "filter" ? "filter" : root.action === "code" ? "code" : "x"`.

In `ui/RuleTag.qml` update the comment to "user accent, generated and dataset yellow, secrets green with a lock, repo and no-kind dim." and make `dataset` share the generated tone:

```qml
  readonly property color tone: rule === "user" ? Color.accent
    : rule === "generated" || rule === "dataset" ? Plugin.Palette.yellow
    : rule === "secrets" ? Plugin.Palette.green
    : Plugin.Tokens.dim
```

and in `border.color` replace `rule === "generated" ?` with `rule === "generated" || rule === "dataset" ?`.

- [ ] **Step 5: Create `ui/FolderTree.qml`**

```qml
import QtQuick
import qs.Commons
import ".." as Plugin
import "../lib/setup.js" as Setup
import "../lib/tree.js" as Tree

// The lazy folder tree of the Folders step and the drive dialog. Top rows come from `folders`;
// a row's children load on its first expand through Service.requestChildren and stay cached
// there, so collapsing only removes rows from the model.
FocusScope {
  id: root

  property var service: null
  property var table: null
  // Top rows: [{path, name, xdg, repo, hasChildren, volume}].
  property var folders: []
  property var choices: Tree.initial([])
  property string home: ""
  property var rates: null
  property string device: "gpu"
  // A drive's mount: its rows read "/name" instead of "~/name".
  property string mount: ""
  property bool locked: false

  signal choicesEdited(var choices)

  property var expanded: ({})
  // Path -> folder row from `folders` or a children reply.
  property var meta: ({})

  readonly property var counts: service ? service.discoverCounts : ({})
  readonly property var walks: service ? service.walks : ({})
  readonly property var datasets: service ? service.datasets : ({})
  readonly property var cached: service ? service.children : ({})
  readonly property int count: list.count
  readonly property var totals: {
    var out = {files: 0, bytes: 0, seconds: 0}
    for (var i = 0; i < folders.length; i++) {
      var kept = Tree.value(folders[i].path, choices, countOf)
      if (!kept) continue
      var estimate = Setup.estimate(kept, rates, device)
      Setup.KINDS.forEach(kind => out.files += kept[kind])
      out.bytes += estimate.bytes
      out.seconds += estimate.seconds
    }
    return out
  }

  function focusFirst() {
    if (!list.count) return false
    list.positionViewAtBeginning()
    list.itemAtIndex(0).focusCheck()
    return true
  }

  function remember(rows) {
    var next = Object.assign({}, meta)
    rows.forEach(row => next[row.path] = row)
    meta = next
  }

  function walkFor(path) {
    var best = ""
    for (var walkRoot in walks) if (Tree.isInside(path, walkRoot) && walkRoot.length > best.length) best = walkRoot
    return best ? walks[best] : null
  }

  // Rolled-up counts, or null while the walk has not reached the folder. A finished walk
  // reports nothing for a folder without indexable files, which is zero.
  function countOf(path) {
    if (counts[path]) return counts[path]
    var row = meta[path]
    if (row && row.counts) return row.counts
    var walk = walkFor(path)
    return walk && walk.done ? {text: 0, pdf: 0, image: 0, video: 0, audio: 0} : null
  }

  function evidenceOf(path) {
    return datasets[path] || (meta[path] && meta[path].evidence) || null
  }

  function label(row, depth) {
    if (depth > 0) return row.name || ""
    if (mount) return row.path.slice(mount.replace(/\/$/, "").length) || "/"
    return Setup.displayPath(row.path, home)
  }

  function indexOf(path) {
    for (var i = 0; i < rows.count; i++) if (rows.get(i).path === path) return i
    return -1
  }

  function insert(index, path, depth) {
    var reply = cached[path]
    var dirs = reply ? reply.dirs : []
    remember(dirs)
    for (var i = 0; i < dirs.length; i++) rows.insert(index + 1 + i, {path: dirs[i].path, depth: depth + 1})
  }

  function toggle(index) {
    var row = rows.get(index)
    var path = row.path
    var depth = row.depth
    var next = Object.assign({}, expanded)
    if (expanded[path]) {
      var end = index + 1
      while (end < rows.count && rows.get(end).depth > depth) end++
      if (end > index + 1) rows.remove(index + 1, end - index - 1)
      delete next[path]
      expanded = next
      return
    }
    next[path] = true
    expanded = next
    if (cached[path]) insert(index, path, depth)
    else if (service) service.requestChildren(path)
  }

  function reload() {
    remember(folders)
    expanded = {}
    rows.clear()
    folders.forEach(folder => rows.append({path: folder.path, depth: 0}))
  }

  onFoldersChanged: reload()
  Component.onCompleted: reload()

  Connections {
    target: root.service
    ignoreUnknownSignals: true
    function onChildrenReceived(path) {
      var index = root.indexOf(path)
      if (index < 0 || !root.expanded[path]) return
      var depth = rows.get(index).depth
      if (index + 1 < rows.count && rows.get(index + 1).depth > depth) return
      root.insert(index, path, depth)
    }
  }

  ListModel { id: rows }

  ListView {
    id: list
    anchors.fill: parent
    clip: true
    model: rows
    boundsBehavior: Flickable.StopAtBounds
    keyNavigationEnabled: false

    delegate: FolderRow {
      id: row
      required path
      required depth
      required property int index
      readonly property var info: root.meta[path] || ({})
      readonly property var found: root.countOf(path)
      readonly property var evidence: root.evidenceOf(path)
      readonly property var kept: Tree.value(path, root.choices, root.countOf)
      readonly property var shown: check === "off" ? found : kept
      readonly property var estimate: check !== "off" && kept ? Setup.estimate(kept, root.rates, root.device) : null
      objectName: "omafindFolderRow"
      width: ListView.view.width
      table: root.table
      enabled: !root.locked
      check: Tree.mark(path, root.choices)
      checkLabel: "Include " + (info.name || path)
      twisty: info.hasChildren ? (root.expanded[path] ? "open" : "closed") : "leaf"
      name: root.label(info, depth)
      rule: evidence ? "dataset" : info.repo ? "repo" : ""
      facts: evidence ? Setup.datasetFacts(evidence) : []
      dash: !shown
      pending: !found
      cells: shown ? Setup.KINDS.map(kind => ({n: shown[kind] || 0, cut: false})) : []
      indexText: estimate ? Setup.mb(estimate.bytes) : ""
      timeText: estimate ? Setup.minutes(estimate.seconds) : ""
      action: info.repo ? "code" : ""
      actionActive: root.choices.code.indexOf(path) >= 0
      actionLabel: "Index the code in " + (info.name || path)
      fill: check === "on" ? "on" : ""
      onToggled: root.choicesEdited(Tree.click(root.choices, path))
      onTwistyClicked: root.toggle(index)
      onActionClicked: root.choicesEdited(Tree.toggleCode(root.choices, path))
      onFocusedChanged: if (focused) ListView.view.positionViewAtIndex(index, ListView.Contain)
      Keys.onRightPressed: if (info.hasChildren && !root.expanded[path]) root.toggle(index)
      Keys.onLeftPressed: if (root.expanded[path]) root.toggle(index)
    }
  }
}
```

- [ ] **Step 6: Rewrite `ui/SetupFolders.qml`**

```qml
import QtQuick
import Quickshell
import qs.Commons
import ".." as Plugin
import "../lib/setup.js" as Setup
import "../lib/tree.js" as Tree

// Step 2: the folder tree, "Add folder" and the totals footer. Choices live here for the session.
FocusScope {
  id: root

  property var service: null
  property var choices: Tree.initial([])
  // Folders added through "Add folder" that sit outside every listed row.
  property var added: []
  // Datasets already offered, so a later walk does not skip one the user checked.
  property var proposed: []
  property bool seeded: false
  property bool picking: false

  signal backRequested()

  readonly property var discover: service ? service.discover : null
  readonly property string home: discover && discover.home ? discover.home : (Quickshell.env("HOME") || "")
  readonly property var rates: discover ? discover.rates : null
  readonly property string device: discover && discover.device ? discover.device : "gpu"
  readonly property var folders: (discover && Array.isArray(discover.folders) ? discover.folders : []).concat(added)
  readonly property var roots: Tree.toRoots(choices.chosen, choices.skipped, volumeOf)
  readonly property bool ready: !!discover && !!service && !service.scanning
    && (roots.length > 0 || choices.code.length > 0) && roots.every(r => r.volume !== "")

  function focusFirst() {
    if (!tree.focusFirst()) {
      if (start.enabled) start.forceActiveFocus()
      else back.forceActiveFocus()
    }
  }

  function seed() {
    if (seeded || !discover || !Array.isArray(discover.folders)) return
    choices = Tree.initial(discover.folders)
    seeded = true
    offerDatasets()
  }

  function offerDatasets() {
    if (!service || !seeded) return
    var list = Object.keys(service.datasets).map(path => service.datasets[path])
    choices = Tree.addDatasets(choices, list, proposed)
    proposed = proposed.concat(list.map(entry => entry.path).filter(path => proposed.indexOf(path) < 0))
  }

  function volumeOf(path) {
    var best = null
    var rows = folders.concat(discover && Array.isArray(discover.roots) ? discover.roots : [])
    rows.forEach(row => {
      var volume = row.volume || (service && service.children[row.path] ? service.children[row.path].volume : "")
      if (volume && Tree.isInside(path, row.path) && (!best || row.path.length > best.path.length))
        best = {path: row.path, volume: volume}
    })
    return best ? best.volume : ""
  }

  function addFolder(path) {
    picking = false
    var absolute = path === "~" ? home : path.indexOf("~/") === 0 ? home + path.slice(1) : path
    if (!folders.some(row => Tree.isInside(absolute, row.path))) {
      added = added.concat([{path: absolute, name: absolute, xdg: false, repo: false, hasChildren: true, volume: ""}])
    }
    if (!Tree.searched(absolute, choices)) choices = Tree.click(choices, absolute)
    // Starts the folder's walk and fetches its volume for saving.
    if (service) service.requestChildren(absolute)
  }

  function startIndexing() {
    service.startIndexing(roots, choices.code)
  }

  onDiscoverChanged: seed()
  Component.onCompleted: seed()

  Connections {
    target: root.service
    ignoreUnknownSignals: true
    function onDatasetsChanged() { root.offerDatasets() }
  }

  FolderTable {
    id: header
    width: parent.width
  }

  FolderTree {
    id: tree
    anchors.top: header.bottom
    anchors.bottom: addRow.top
    width: parent.width
    service: root.service
    table: header
    folders: root.folders
    choices: root.choices
    home: root.home
    rates: root.rates
    device: root.device
    onChoicesEdited: next => root.choices = next
  }

  Item {
    id: addRow
    anchors.bottom: footer.top
    anchors.bottomMargin: Plugin.Tokens.setupGap
    width: parent.width
    height: Style.space(12) + Math.max(addFolder.height, picker.visible ? picker.implicitHeight : 0)

    ActionButton {
      id: addFolder
      visible: !root.picking
      objectName: "omafindAddFolder"
      x: Plugin.Tokens.tablePadding
      y: Style.space(12)
      text: "Add folder"
      icon: "plus"
      focusable: true
      buttonHeight: Style.space(28)
      onClicked: {
        root.picking = true
        picker.reset()
        Qt.callLater(picker.focusField)
      }
    }

    PathField {
      id: picker
      visible: root.picking
      x: Plugin.Tokens.tablePadding
      y: Style.space(12)
      width: parent.width - 2 * x
      service: root.service
      onAdded: path => root.addFolder(path)
      onCancelled: {
        root.picking = false
        addFolder.forceActiveFocus()
      }
    }
  }

  Column {
    id: footer
    anchors.bottom: parent.bottom
    width: parent.width
    spacing: Plugin.Tokens.setupGap

    Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }

    Label {
      visible: !!root.service && root.service.setupError !== ""
      width: parent.width
      wrapMode: Text.Wrap
      text: root.service ? root.service.setupError : ""
      color: Color.urgent
    }

    Item {
      width: parent.width
      height: Style.space(32)

      SetupFacts {
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        width: Math.min(implicitWidth, parent.width - buttons.width - Style.space(8))
        fontSize: Style.font.body
        gap: Style.space(18)
        // The board bolds the count of `selected`, not the word "files".
        tokens: root.discover ? Setup.totalFacts(tree.totals, root.device).map(t => t.k === "selected"
          ? {k: t.k, v: String(t.v).replace(/^([\d,]+)/, "<b>$1</b>"), tone: "plain"} : t) : []
      }

      Row {
        id: buttons
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(8)

        ActionButton {
          id: back
          objectName: "omafindSetupBack"
          text: "Back"
          focusable: true
          onClicked: root.backRequested()
        }

        ActionButton {
          id: start
          objectName: "omafindSetupStart"
          text: "Start indexing"
          primary: true
          neutral: true
          focusable: true
          enabled: root.ready && !root.service.indexPending
          onClicked: root.startIndexing()
        }
      }
    }
  }
}
```

- [ ] **Step 7: Drop the tree sub-view from `SetupView.qml`**

Delete the properties `sub` and `treeRoot`, the alias `tree`, the functions `showTree` and `closeTree`, every `foldersPage.prefetch()` call, the `Connections` block that calls `prefetch`, and the last `Swap` holding `treeLoader`. Then:

```qml
  readonly property var size: Setup.panelSize(step)
  readonly property real panelWidth: Style.space(size.width)
  readonly property real panelHeight: Style.space(size.height) + (step === 3 ? indexPage.extraHeight : 0)
  readonly property string walkError: service ? Setup.walkError(service.walks) : ""
```

```qml
  function reset() {
    back = false
  }

  function focusFirst() {
    if (step === 1) enginePage.focusFirst()
    else if (step === 2) foldersPage.focusFirst()
    else indexPage.focusFirst()
  }

  function handleKey(event) {
    if (event.key === Qt.Key_Escape) {
      root.closeRequested()
      event.accepted = true
    }
  }

  onStepChanged: {
    if (step === 2) ensureScan()
    if (step === 3) indexPage.begin()
    Qt.callLater(focusFirst)
  }

  Component.onCompleted: {
    if (step === 2) ensureScan()
    if (step === 3) indexPage.begin()
  }
```

Every `shown: root.sub === ""`, `root.step === 2 && root.sub === ""` becomes `shown: true` and `root.step === 2`. In `Parts.SetupFolders` delete `onTreeRequested`. In the `SetupHeader` replace `subtitle`, `subtitleColor`, `spinning` and `facts`:

```qml
          subtitle: root.step === 1 ? "Everything runs on this machine. Nothing downloads until you press a button."
            : root.step === 3 ? root.indexFailure || "You can search already. Results fill in as files finish."
            : root.service && !root.service.scanning && root.service.discoverError !== "" ? root.service.discoverError
            : root.walkError !== "" ? "File counts stopped: " + root.walkError + ". You can still pick folders and start indexing."
            : ""
          subtitleColor: root.step === 2 || root.indexFailure !== "" ? Color.urgent : Plugin.Tokens.dim
          spinning: root.step === 2 && !!root.service && (root.service.scanning
            || Object.keys(root.service.walks).some(key => !root.service.walks[key].done))
          facts: root.step !== 2 || !root.discover ? []
            : Setup.scanFacts(foldersPage.folders.length, root.service.walks)
```

Update the header comment to: "The first-run flow (boards Setup, Discover, Indexing; motion M3). The step comes from daemon facts; only "Back" is local. Overlay sizes the card from panelWidth and panelHeight."

- [ ] **Step 8: Run the checks**

Run: `scripts/qmllint.sh && node --test "tests/js/*.test.mjs" && uv run --project helper pytest -q tests/helper/test_qml_text.py`
Expected: exit 0 and all pass. Fix any `unqualified access` warning qmllint reports in the new files by prefixing with `root.`.

- [ ] **Step 9: Commit**

```bash
git add ui/FolderTree.qml ui/SetupFolders.qml ui/FolderRow.qml ui/RuleTag.qml SetupView.qml lib/setup.js tests/js/setup.test.mjs
git commit -m "feat(setup): pick folders from a lazy tree that counts as it walks"
```

### Task 13: Drive dialog on the shared tree, and the ledger removed

**Files:**
- Modify: `ui/DriveDialog.qml` (logic lines 1-224, folder table lines 296-341, the `Loader` at 458-483), `ui/FolderRow.qml`, `Tokens.qml`, `lib/setup.js` (`totals`), `helper/omafindd/rules.py` (`removed`, `explain`, `rule_dirs`, `secret_family`)
- Delete: `ui/LeftOutLedger.qml`, `ui/SetupLeaveOut.qml`, `ui/LedgerFooter.qml`, `ui/KindBar.qml`, `ui/Hatch.qml`, `lib/ledger.js`, `lib/ledgerTree.js`, `tests/js/ledger.test.mjs`, `tests/js/ledgerTree.test.mjs`, `tests/fixtures/setup/documents-tree.json`, `helper/omafindd/leftout.py`, `tests/helper/test_leftout.py`
- Test: `tests/js/setup.test.mjs`, `tests/helper/test_rules.py`, `tests/helper/test_discovery.py:97-107`, `tests/helper/test_cli.py:428-435`

**Interfaces:**
- Consumes: `FolderTree` (Task 12), `Service.walks`, `Service.driveDiscover` (a `discover_result` with `volume` set; Task 9 shape), `Tree.toRoots`, `Tree.click`.
- Produces: the drive dialog offers the drive's top folders, all checked, through `FolderTree` with `mount` set; `Volumes.driveFacts` gets `{running: true}` or `{seconds}` from `service.walks[mount]`.
- Removes: `Setup.totals`; `FolderRow` properties `connector`, `dirPrefix`, `showBar`, `segments`, `barWidth`, `caret`, `undo`, `hatched`, `ruleTop` and signals `caretClicked`, `undoClicked`; `Tokens.leftOutRow`, `leftOutHead`, `treeRow`.

- [ ] **Step 1: Rewrite the drive dialog's state**

In `ui/DriveDialog.qml` replace the imports and everything from `property var service: null` down to the end of `startIndexing()` with:

```qml
import QtQuick
import qs.Commons
import ".." as Plugin
import "../lib/setup.js" as Setup
import "../lib/tree.js" as Tree
import "../lib/volumes.js" as Volumes
```

```qml
  property var service: null
  property string uuid: ""
  property var choices: Tree.initial([])
  property bool seeded: false
  // "pick", then "run" after Index this drive, then "done".
  property string phase: "pick"
  property bool sawProgress: false

  signal closeRequested()

  readonly property var volume: service && service.volumes.drives[uuid] ? service.volumes.drives[uuid]
    : ({uuid: uuid, label: "", fs: "", size: 0, mount: null})
  readonly property var discover: service && service.driveDiscover && service.driveDiscover.volume === uuid
    ? service.driveDiscover : null
  readonly property string mount: volume.mount || (discover && discover.roots && discover.roots.length
    ? discover.roots[0].path : "")
  readonly property string label: Volumes.driveLabel({uuid: uuid, label: volume.label, mount: mount})
  readonly property bool scanning: !!service && service.driveScanning
  readonly property var folders: discover && Array.isArray(discover.folders) ? discover.folders : []
  readonly property var walk: service && mount && service.walks[mount] ? service.walks[mount] : null
  readonly property var rates: discover ? discover.rates : null
  readonly property string device: discover && discover.device ? discover.device : "gpu"
  readonly property bool anyChecked: choices.chosen.length > 0
  readonly property var progress: service ? service.progress : null
  readonly property var footer: Volumes.dialogFooter(progress, uuid, label)
  readonly property string errorText: service ? service.setupError || service.driveError : ""

  readonly property real panelWidth: Style.space(1120)
  // The 4 covers the card border on both edges.
  readonly property real panelHeight: body.implicitHeight + 2 * Plugin.Tokens.setupPadding + 4

  function reset() {
    choices = Tree.initial([])
    seeded = false
    phase = "pick"
    sawProgress = false
    closeTimer.stop()
  }

  function begin() {
    if (service && uuid) service.scanDrive(uuid)
  }

  function focusFirst() {
    if (tree.focusFirst()) return
    if (start.enabled) start.forceActiveFocus()
    else cancel.forceActiveFocus()
  }

  function handleKey(event) {
    if (event.key === Qt.Key_Escape) {
      root.closeRequested()
      event.accepted = true
    }
  }

  // Every folder on the drive starts checked.
  function seed() {
    if (seeded || !folders.length) return
    choices = {chosen: folders.map(folder => folder.path), skipped: [], code: []}
    seeded = true
  }

  function seconds(value) {
    return value < 90 ? Math.round(value) + " s" : Math.round(value / 60) + " min"
  }

  // Appends the chosen folders to `roots` under this volume, replacing any root at the same path.
  function startIndexing() {
    var fresh = Tree.toRoots(choices.chosen, choices.skipped, () => root.uuid)
    var paths = fresh.map(r => r.path)
    var roots = service.settings.roots.filter(r => paths.indexOf(r.path) < 0).concat(fresh)
    if (!service.startIndexing(roots, null, uuid)) return
    sawProgress = false
    phase = "run"
  }

  onFoldersChanged: seed()
```

Keep the `finished` property, `onFinishedChanged`, `onUuidChanged`, `Component.onCompleted`, the `Connections` and `closeTimer` as they are.

- [ ] **Step 2: Replace the folder table**

Remove `opacity: root.sub === "" ? 1 : 0`, `visible: opacity > 0`, `enabled: root.sub === ""` and the `Behavior on opacity` from the content `Item` (the dialog has one view now). In the head `SetupFacts` replace `tokens:` with:

```qml
            tokens: Volumes.driveFacts({mount: root.mount, fs: root.volume.fs},
              root.scanning || (root.walk && !root.walk.done) ? {running: true}
              : root.walk ? {seconds: root.walk.seconds || 0} : null)
```

Replace the `Column` that holds `FolderTable { id: header ... }`, the `Repeater` and the dataset `Item` with:

```qml
      Column {
        width: parent.width

        FolderTable {
          id: header
          width: parent.width
          folderLabel: "Folder on the drive"
        }

        FolderTree {
          id: tree
          width: parent.width
          height: Math.max(1, Math.min(tree.count, 10)) * Plugin.Tokens.tableRow
          service: root.service
          table: header
          folders: root.folders
          choices: root.choices
          mount: root.mount
          rates: root.rates
          device: root.device
          locked: root.phase !== "pick"
          onChoicesEdited: next => root.choices = next
        }
      }
```

In the totals `SetupFacts` replace `root.totals` with `tree.totals` (three places). Change the `start` button's `enabled` to `!!root.discover && !root.scanning && root.anyChecked && !!root.service && !root.service.indexPending`. Delete the trailing `Loader { id: treeLoader ... }`.

- [ ] **Step 3: Remove the ledger code and its tests**

```bash
git rm ui/LeftOutLedger.qml ui/SetupLeaveOut.qml ui/LedgerFooter.qml ui/KindBar.qml ui/Hatch.qml \
  lib/ledger.js lib/ledgerTree.js tests/js/ledger.test.mjs tests/js/ledgerTree.test.mjs \
  tests/fixtures/setup/documents-tree.json helper/omafindd/leftout.py tests/helper/test_leftout.py
grep -rn "LeftOutLedger\|SetupLeaveOut\|LedgerFooter\|KindBar\|Hatch\b\|ledger\.js\|ledgerTree\|leftout" \
  --include=*.qml --include=*.js --include=*.py --include=*.mjs . | grep -v '^./docs/'
```

Expected: only `tests/helper/test_cli.py` (the stdlib import test). There change `'from omafindd import discovery, leftout, selection, rules'` to `'from omafindd import discovery, selection, rules'`.

In `ui/FolderRow.qml` delete the properties `connector`, `dirPrefix`, `showBar`, `segments`, `barWidth`, `caret`, `undo`, `hatched`, `ruleTop`, the signals `caretClicked` and `undoClicked`, `readonly property real topGap` and every block that reads them: the dashed `Row` (`visible: root.ruleTop`), the connector `Item`, the `KindBar`, the caret spacer `Item` and caret `Icon`, the "Undo" `Label` and its key-cap `Row`, and the `Hatch`. Replace `y: root.topGap` with `y: 0` (or drop the line), `implicitHeight: rowHeight + topGap` with `implicitHeight: rowHeight`, the name `Label`'s `text:` with `root.name` and its `textFormat` with `Text.PlainText`, and drop `!root.hatched &&` from the Index and Time cells. Update the header comment to "`.dt-r`: one folder table row, laid out on a FolderTable's columns." Then:

```bash
grep -n "connector\|dirPrefix\|showBar\|segments\|barWidth\|caret\|undo\|hatched\|ruleTop\|topGap\|KindBar\|Hatch" ui/FolderRow.qml
```

Expected: no output.

In `Tokens.qml` delete `leftOutRow`, `leftOutHead` and `treeRow` after `grep -rn "leftOutRow\|leftOutHead\|treeRow" --include=*.qml .` shows only `Tokens.qml`.

- [ ] **Step 4: Remove `Setup.totals`**

Delete `function totals(...)` from `lib/setup.js`. In `tests/js/setup.test.mjs` replace `totals only include checked content and recompute estimates` with:

```js
test('total facts and estimates use kind rates', () => {
  assert.deepEqual(values(s.totalFacts({files:1209,bytes:13606000,seconds:147.51},'gpu')), [['selected','1,209 files'],['index','14 MB'],['time','~2 min'],['device','GPU']]);
  assert.deepEqual(plain(s.estimate({text:2,pdf:0,image:0,video:0,audio:0},discover.rates,'cpu')), {bytes:22000,seconds:.26});
});
```

and delete the line `assert.deepEqual(plain(s.totals(null, null, 'gpu')), {files: 0, bytes: 0, seconds: 0});` from `estimates and problem facts tolerate data that has not arrived`.

- [ ] **Step 5: Remove the scan-only rule helpers**

```bash
grep -rn "removed(\|explain(\|rule_dirs\|secret_family" helper bin scripts tests | grep -v "def "
```

Expected: only tests. Delete `removed`, `explain`, `rule_dirs` and `secret_family` from `helper/omafindd/rules.py`. In `tests/helper/test_rules.py` delete `test_explain_unchanged_after_refactor`, `test_secret_family_names`, `test_explain_keeps_existing_hidden_secret_counts` and `test_rule_directory_counts_do_not_need_a_baseline`, and replace `test_explain_counts_names_without_opening_files` with:

```python
def test_walk_leaves_out_hidden_heavy_and_secret_names(tmp_path):
    from omafindd.rules import walk

    (tmp_path / "visible.txt").write_text("fixture")
    (tmp_path / ".hidden.txt").write_text("fixture")
    (tmp_path / "secret.txt").write_text("fixture")
    (tmp_path / "build").mkdir()
    (tmp_path / "build/a.txt").write_text("fixture")
    assert list(walk(tmp_path, excludes=[])) == [tmp_path / "visible.txt"]
```

In `tests/helper/test_discovery.py` delete `test_explain_counts_dot_heavy_secrets_by_name`.

- [ ] **Step 6: Run the checks**

Run: `uv run --project helper pytest -q && node --test "tests/js/*.test.mjs" && scripts/qmllint.sh && uv run --project helper ruff check helper tests bin/omafind scripts`
Expected: all pass; ruff clean (drop any import it reports unused).

- [ ] **Step 7: Commit**

```bash
git add -A ui lib tests helper Tokens.qml
git status --short
git commit -m "refactor(setup): show drives in the shared tree and drop the ledger"
```

Read `git status --short` before committing: it must list only the files of this task.

---

### Task 14: `binds_get` and lone function-key shortcuts

**Files:**
- Modify: `helper/omafindd/bindings.py:52-67`, `helper/omafindd/setup.py` (TYPES, constructor `run`, `handle`, error codes), `helper/omafindd/settings.py:30-37`, `lib/Settings.js:22-31`, `bin/omafind:465-475`, `docs/ipc.md:129-132` and setup table, `README.md:71,157`
- Test: `tests/helper/test_bindings.py:37-52`, `tests/helper/test_ipc_setup.py`, `tests/helper/test_settings.py`, `tests/js/settings.test.mjs:69-74`

**Interfaces:**
- Produces: `bindings.chord_label(mods: int, key: str) -> str` (`"Super Shift E"`, modifier order Super, Ctrl, Shift, Alt; key names `Space`, `Comma`, `Period`, `Return`, `Escape`, `Tab`, `F1`..`F35`, letters and digits uppercase).
- Produces: `bindings.binds_items(binds: list[Bind]) -> list[{"chord": str, "description": str}]`, skipping omafind's own bind and empty keys, first entry per chord.
- Produces: request `{"t":"binds_get"}` replies `{"t":"binds","binds":[{"chord","description"}]}`; failure replies `{"t":"error","for":"binds_get","code":"binds-failed","reason":...}`.
- Produces: `valid_shortcut` and `Settings.shortcut` accept a lone `F1` to `F35` as well as `MODS + KEY`.
- Removes: `bindings.first_free` and the CLI's "Try X." suggestion.

- [ ] **Step 1: Write the failing tests**

In `tests/helper/test_bindings.py` replace `test_cli_conflict_and_fallback` with:

```python
def test_cli_conflict_names_the_holder_without_suggesting(cli, env, capsys):
    values = [{"modmask": 64, "key": "E", "description": "Taken"}]

    def run(argv, **kwargs):
        assert argv == ["hyprctl", "binds", "-j"]
        assert kwargs["timeout"]
        return subprocess.CompletedProcess(argv, 0, json.dumps(values), "")

    assert cli.main(["bindings", "check", "--chord", "SUPER + E"], env, run=run) == 2
    assert capsys.readouterr().out == "Super E is taken by Taken.\n"


def test_binds_items_label_chords_and_skip_ours_and_empty_keys():
    values = [{"modmask": 64, "key": "e", "description": "omafind"},
              {"modmask": 65, "key": "SPACE", "description": "Launcher"},
              {"modmask": 76, "key": "h", "description": "Hardware"},
              {"modmask": 64, "key": "", "description": "Workspace"},
              {"modmask": 0, "key": "F9", "description": ""},
              {"modmask": 65, "key": "space", "description": "Second"},
              {"modmask": 64, "key": "R", "description": "resize", "submap": "resize"}]
    assert bindings.binds_items(bindings.parse_binds(json.dumps(values))) == [
        {"chord": "Super Shift Space", "description": "Launcher"},
        {"chord": "Super Ctrl Alt H", "description": "Hardware"},
        {"chord": "F9", "description": ""},
    ]
```

Append to `tests/helper/test_ipc_setup.py`:

```python
async def test_binds_get_returns_live_binds(service):
    import subprocess

    calls = []

    def run(argv, **kw):
        calls.append((argv, kw))
        return subprocess.CompletedProcess(
            argv, 0, json.dumps([{"modmask": 64, "key": "D", "description": "Files"}]), "")

    service.run = run
    assert await service.handle({"t": "binds_get"}) == {
        "t": "binds", "binds": [{"chord": "Super D", "description": "Files"}]}
    assert calls[0][0] == ["hyprctl", "binds", "-j"] and calls[0][1]["timeout"] == 5


async def test_binds_get_failure_names_the_request(service):
    def run(argv, **kw):
        raise FileNotFoundError("hyprctl")

    service.run = run
    reply = await service.handle({"t": "binds_get"})
    assert reply["t"] == "error" and reply["for"] == "binds_get"
    assert reply["code"] == "binds-failed"
    assert reply["reason"].startswith("Could not read your Hyprland bindings")
```

In `tests/helper/test_settings.py` add:

```python
@pytest.mark.parametrize("value,valid", [("F9", True), ("F35", True), ("SUPER + F9", True),
                                         ("F36", False), ("F0", False), ("E", False),
                                         ("SUPER + SHIFT + SPACE", True)])
def test_shortcut_accepts_a_lone_function_key(value, valid):
    from omafindd.settings import valid_shortcut

    assert valid_shortcut(value) is valid
```

(add `import pytest` at the top if the file lacks it). In `tests/js/settings.test.mjs` extend `shortcut accepts MODS + KEY and falls back otherwise`:

```js
  for (const value of ['F9', 'F35', 'SUPER + F9']) assert.equal(normalize({ shortcut: value }).shortcut, value);
  for (const value of ['F36', 'F0']) assert.equal(normalize({ shortcut: value }).shortcut, 'SUPER + E');
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project helper pytest -q tests/helper/test_bindings.py tests/helper/test_ipc_setup.py tests/helper/test_settings.py && node --test tests/js/settings.test.mjs`
Expected: FAIL (`binds_items` missing, "Try Super D." still printed, `binds_get` unknown, `F9` invalid).

- [ ] **Step 3: Implement**

`helper/omafindd/settings.py`:

```python
_MODS = r"(?:SUPER|SHIFT|CTRL|ALT)"


def valid_shortcut(value) -> bool:
    """`MODS + KEY` in uppercase, or a lone function key F1 to F35."""
    if not isinstance(value, str) or not re.fullmatch(
        rf"{_MODS}(?:\s*\+\s*{_MODS})*\s*\+\s*[A-Z0-9_]+|F(?:[1-9]|[12][0-9]|3[0-5])", value
    ):
        return False
    parts = [part.strip() for part in value.split("+")]
    return len(set(parts)) == len(parts) and parts[-1] not in ("SUPER", "SHIFT", "CTRL", "ALT")
```

`lib/Settings.js` `shortcut`:

```js
// Mirrors valid_shortcut in helper/omafindd/settings.py.
function shortcut(value) {
  if (typeof value !== "string"
      || !/^(?:(?:SUPER|SHIFT|CTRL|ALT)(?:\s*\+\s*(?:SUPER|SHIFT|CTRL|ALT))*\s*\+\s*[A-Z0-9_]+|F(?:[1-9]|[12][0-9]|3[0-5]))$/.test(value)) {
    return "SUPER + E"
  }
```

(the rest of the function stays).

`helper/omafindd/bindings.py`: replace `first_free` with:

```python
_LABELS = (("SUPER", "Super"), ("CTRL", "Ctrl"), ("SHIFT", "Shift"), ("ALT", "Alt"))
_KEY_NAMES = {"SPACE": "Space", "COMMA": "Comma", "PERIOD": "Period", "RETURN": "Return",
              "ESCAPE": "Escape", "TAB": "Tab"}


def chord_label(mods, key):
    """The overlay's name for a chord, as lib/keycombo.js label() writes it."""
    upper = key.upper()
    name = _KEY_NAMES.get(upper, upper if re.fullmatch(r"[A-Z0-9]|F\d{1,2}", upper) else key)
    return " ".join([label for token, label in _LABELS if mods & MODIFIERS[token]] + [name])


def binds_items(binds) -> list[dict]:
    """Live binds as `{chord, description}`, without omafind's own bind or empty keys."""
    items, seen = [], set()
    for bind in binds:
        if bind.ours or not bind.key:
            continue
        chord = chord_label(bind.mods, bind.key)
        if chord not in seen:
            seen.add(chord)
            items.append({"chord": chord, "description": bind.description})
    return items
```

`bin/omafind` in the `check` branch replace the conflict lines:

```python
        if result == "conflict":
            holder = next(bind for bind in module.matching(chord, values) if not bind.ours)
            print(f"{display} is taken by {holder.description or holder.key}.")
            return 2
```

`helper/omafindd/setup.py`: add `"binds_get",` to `TYPES`; add the keyword `run=subprocess.run,` to the constructor and `self.run = run`; add `from . import bindings` next to `from . import discovery`; in `handle` before `if kind == "discover_start":`:

```python
            if kind == "binds_get":
                return await asyncio.to_thread(self._binds)
```

and the method:

```python
    def _binds(self):
        try:
            result = self.run(["hyprctl", "binds", "-j"], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as error:
            raise OSError(f"Could not read your Hyprland bindings: {error}.") from error
        if result.returncode:
            detail = result.stderr.strip() or f"hyprctl exited with {result.returncode}"
            raise OSError(f"Could not read your Hyprland bindings: {detail}.")
        return {"t": "binds", "binds": bindings.binds_items(bindings.parse_binds(result.stdout))}
```

and in the `except Exception` code mapping:

```python
            code = (
                "runtime-failed"
                if kind.startswith("runtime_") or kind == "index_start"
                else "binds-failed" if kind == "binds_get"
                else "scan-failed"
            )
```

- [ ] **Step 4: Run tests**

Run: `uv run --project helper pytest -q && node --test "tests/js/*.test.mjs"`
Expected: PASS.

- [ ] **Step 5: Document it**

`docs/ipc.md` lines 129-132:

```markdown
`shortcut` is a string, default `"SUPER + E"`. It is one or more uppercase
modifiers (`SUPER`, `SHIFT`, `CTRL`, `ALT`) followed by `+` and an uppercase key
name (letters, digits or underscores), or a lone function key `F1` to `F35`.
Duplicate modifiers and a modifier used as the key are invalid. Invalid values
fall back to the default.
```

Setup table row:

```markdown
| `binds_get` | `binds` | none; reads `hyprctl binds -j` |
```

and after the `fs_list` bullets:

````markdown
```
plugin: {"t":"binds_get"}
daemon: {"t":"binds","binds":[{"chord":"Super Shift Space","description":"Launcher"},{"chord":"F9","description":""}]}
```
- Live global binds, labeled the way the overlay labels a captured chord: modifiers in the order Super, Ctrl, Shift, Alt, then the key (`Space`, `Comma`, `Period`, `Return`, `Escape`, `Tab`, `F1` to `F35`, letters and digits). Submap binds, binds with an empty key and omafind's own bind are left out. A failure replies `error` with `code:"binds-failed"`.
````

Add `binds-failed` to the "Error codes" bullet. README line 71: `| \`shortcut\` | uppercase \`MODS + KEY\` (mods: SUPER, SHIFT, CTRL, ALT) or a lone \`F1\` to \`F35\` | \`"SUPER + E"\` |`. README line 157: replace "`check` reports conflicts and suggests a free shortcut." with "`check` reports whether the shortcut is free, bound by omafind or taken, and by what." `settings.example.json` keeps `"shortcut": "SUPER + E"`; the key is unchanged.

- [ ] **Step 6: Lint and commit**

Run: `uv run --project helper ruff check helper tests bin/omafind scripts`
Expected: "All checks passed!".

```bash
git add helper/omafindd/bindings.py helper/omafindd/setup.py helper/omafindd/settings.py lib/Settings.js bin/omafind docs/ipc.md README.md tests
git commit -m "feat(omafindd): list live hyprland binds for shortcut capture"
```

### Task 15: `lib/keycombo.js`

**Files:**
- Create: `lib/keycombo.js` (port of `/home/radimsem/personal/projects/omaone/lib/keycombo.js`)
- Test: `tests/js/keycombo.test.mjs`

**Interfaces:**
- Consumes: the `binds` reply shape from Task 14.
- Produces:
  - `comboFromQt(key, modifiers) -> string[] | "cancel" | null` (`["Super", "Shift", "H"]`; Esc alone or with Super cancels).
  - `toHyprland(parts) -> "SUPER + SHIFT + H"`, `fromHyprland(text) -> parts` (`[]` when invalid), `label(parts) -> "Super Shift H"`.
  - `bindMap(list: [{chord, description}]) -> {chord: description}` (first entry wins).
  - `checkCombo(parts, binds) -> string | null`: the sentence to show, or null when the chord is usable.
  - `recordingSubmapLost(active, operation, submap) -> bool`.
  - `recordCommand(nonce, leave) -> argv` for the `omafind-record` submap.

- [ ] **Step 1: Write the failing tests**

`tests/js/keycombo.test.mjs`:

```js
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
    [['Ctrl', 'F9'], 'Ctrl F9 is already bound to Dictation in Hyprland. Press another shortcut.'],
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test tests/js/keycombo.test.mjs`
Expected: FAIL with ENOENT for `lib/keycombo.js`.

- [ ] **Step 3: Write `lib/keycombo.js`**

```js
.pragma library

// Shortcut capture, ported from omaone: Qt key events to chords, Hyprland chord strings, the
// conflict sentence and the script that holds Hyprland in the omafind-record submap.
var MODIFIERS = ["Super", "Ctrl", "Shift", "Alt"]
var QT_MODIFIERS = [0x10000000, 0x04000000, 0x02000000, 0x08000000]
var KEY_NAMES = {ESCAPE: "Escape", TAB: "Tab", RETURN: "Return", SPACE: "Space",
  COMMA: "Comma", PERIOD: "Period"}
var FUNCTION_KEY = /^F([1-9]|[12][0-9]|3[0-5])$/

function comboFromQt(key, modifiers) {
  var name = null
  if (key === 0x01000000) name = "Escape"
  else if (key === 0x01000001) name = "Tab"
  else if (key === 0x01000004 || key === 0x01000005) name = "Return"
  else if (key === 0x20) name = "Space"
  else if (key === 0x2c) name = "Comma"
  else if (key === 0x2e) name = "Period"
  else if (key >= 0x01000030 && key <= 0x01000052) name = "F" + (key - 0x01000030 + 1)
  else if ((key >= 0x41 && key <= 0x5a) || (key >= 0x30 && key <= 0x39)) name = String.fromCharCode(key)
  if (name === null) return null
  var parts = []
  for (var i = 0; i < MODIFIERS.length; i++) {
    if (modifiers & QT_MODIFIERS[i]) parts.push(MODIFIERS[i])
  }
  if (name === "Escape" && (parts.length === 0 || parts[0] === "Super")) return "cancel"
  parts.push(name)
  return parts
}

function toHyprland(parts) {
  return parts.join(" + ").toUpperCase()
}

function fromHyprland(text) {
  if (typeof text !== "string" || !text.trim()) return []
  var tokens = text.toUpperCase().split("+")
  var modifiers = {}
  var key = null
  for (var i = 0; i < tokens.length; i++) {
    var token = tokens[i].trim()
    var modifier = token === "SUPER" ? "Super" : token === "CTRL" ? "Ctrl" :
      token === "SHIFT" ? "Shift" : token === "ALT" ? "Alt" : null
    if (modifier) modifiers[modifier] = true
    else {
      if (key !== null) return []
      key = Object.prototype.hasOwnProperty.call(KEY_NAMES, token) ? KEY_NAMES[token] :
        /^[A-Z0-9]$/.test(token) || FUNCTION_KEY.test(token) ? token : null
      if (key === null) return []
    }
  }
  if (key === null) return []
  var parts = []
  for (var j = 0; j < MODIFIERS.length; j++) {
    if (modifiers[MODIFIERS[j]]) parts.push(MODIFIERS[j])
  }
  parts.push(key)
  return parts
}

function label(parts) {
  return parts.join(" ")
}

// `binds_get` items as {chord label: description}.
function bindMap(list) {
  var map = {}
  ;(list || []).forEach(function(bind) {
    if (!Object.prototype.hasOwnProperty.call(map, bind.chord)) map[bind.chord] = bind.description || ""
  })
  return map
}

function recordingSubmapLost(active, operation, submap) {
  return active !== "" && operation === "entered" && submap.trim() !== "omafind-record"
}

// The sentence for a chord the user cannot take, or null. omafind's own bind never appears in
// `binds`, so the current shortcut checks as free.
function checkCombo(parts, binds) {
  var name = label(parts)
  if (parts[0] !== "Super" && !FUNCTION_KEY.test(parts[parts.length - 1])) {
    return name + " would fire while you type. Add Super and try again."
  }
  if (Object.prototype.hasOwnProperty.call(binds, name)) {
    return name + (binds[name] ? " is already bound to " + binds[name] + " in Hyprland. Press another shortcut."
      : " is already bound in Hyprland. Press another shortcut.")
  }
  // hyprctl reports Omarchy's workspace binds with an empty key, so Super plus a digit never shows up in binds.
  if (parts[0] === "Super" && /^[0-9]$/.test(parts[parts.length - 1])) {
    return name + " is already bound in Hyprland. Press another shortcut."
  }
  return null
}

function recordCommand(nonce, leave) {
  var lock = "umask 077\nrecord=\"${XDG_RUNTIME_DIR:?}/omafind-record\"\n"
    + "exec 9>\"$record.lock\"\nflock -x 9 || exit 1\n"
  var cleanup = "if [ \"$(cat \"$record\" 2>/dev/null)\" = \"$1\" ]; then\n"
    + "  rm -f \"$record\"\n"
    + "  if [ \"$(hyprctl submap 2>/dev/null)\" = omafind-record ]; then\n"
    + "    hyprctl dispatch 'hl.dsp.submap(\"reset\")' >/dev/null 2>&1\n"
    + "  fi\nfi\n"
  if (leave) {
    // A destroyed recorder can queue cleanup before its enter script reaches the lock.
    return ["sh", "-c", lock
      + "if [ \"$(cat \"$record\" 2>/dev/null)\" != \"$1\" ]; then : > \"$record.$1.cancel\"; fi\n"
      + cleanup, "omafind-record", nonce]
  }
  var watchdog = "sleep 31\n" + lock + cleanup + "rm -f \"$record.$1.cancel\"\n"
  return ["sh", "-c", lock
    + "if [ -e \"$record.$1.cancel\" ]; then rm -f \"$record.$1.cancel\"; exit 0; fi\n"
    + "printf '%s\\n' \"$1\" > \"$record\" || exit 1\n"
    // Closing fd 9 keeps the detached watchdog from retaining the enter script's lock.
    + "setsid -f sh -c '" + watchdog.replace(/'/g, "'\\''") + "' omafind-watchdog \"$1\" 9>&- >/dev/null 2>&1\n"
    + "if ! hyprctl binds -j 2>/dev/null | jq -e 'any(.[]; .submap == \"omafind-record\" and (.key // \"\" | ascii_upcase) == \"ESCAPE\" and .modmask == 64)' >/dev/null 2>&1; then\n"
    + "  hyprctl eval 'hl.define_submap(\"omafind-record\", function() hl.bind(\"SUPER + F24\", hl.dsp.no_op()); hl.bind(\"SUPER + ESCAPE\", hl.dsp.submap(\"reset\"), { non_consuming = true }) end)' >/dev/null 2>&1\n"
    + "fi\nhyprctl dispatch 'hl.dsp.submap(\"omafind-record\")' >/dev/null 2>&1\n"
    + "hyprctl submap 2>/dev/null", "omafind-record", nonce]
}
```

- [ ] **Step 4: Run tests**

Run: `node --test tests/js/keycombo.test.mjs`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/keycombo.js tests/js/keycombo.test.mjs
git commit -m "feat(setup): port shortcut capture logic from omaone"
```

---

### Task 16: Record the shortcut in the Index step

**Files:**
- Create: `ui/ShortcutRow.qml`, `ui/ShortcutRecorder.qml`
- Modify: `ui/SetupIndex.qml:20-74,260-326,417`, `Service.qml:44,214-221,338-391,504-522`, `lib/setup.js:5,258-281`
- Test: `tests/js/setup.test.mjs:104-116`

**Interfaces:**
- Consumes: `Keycombo.*` (Task 15), `binds_get` (Task 14), `Service.saveShortcut(chord, menuRow, done)` (unchanged).
- Produces on `Service`: `binds: var` (the reply list), `bindsReady: bool`, `bindsError: string`, `getBinds()`.
- Produces: `ShortcutRow { parts; prompt; recording; canChange; note; noteTone; signal change(); signal cancel(); signal captured(int key, int modifiers); function take() }`.
- Produces: `ShortcutRecorder { binds; readonly active; conflict; exposed; lost; signal recorded(string chord); function start(); function stop(); function capture(key, modifiers) }`.
- Removes: `Service.bindingChecks`, `checkBindings`, the `bindingProcess` component; `Setup.CHORDS`, `chordKeys`, `shortcutLine`, `nextChord`.

- [ ] **Step 1: Delete the chord-list test**

In `tests/js/setup.test.mjs` delete `shortcut checks handle free ours conflict pending and cycling`.

- [ ] **Step 2: Remove the hard-coded chords from `lib/setup.js`**

Delete `var CHORDS = [...]`, `chordKeys`, `shortcutLine` and `nextChord`.

Run: `node --test tests/js/setup.test.mjs && grep -rn "CHORDS\|chordKeys\|shortcutLine\|nextChord\|first_free" --include=*.js --include=*.qml --include=*.py --include=*.mjs . bin`
Expected: tests pass; grep lists only `ui/SetupIndex.qml`, which Step 5 rewrites.

- [ ] **Step 3: Service binds**

In `Service.qml` replace `property var bindingChecks: ({})` with:

```qml
  // binds_get reply: [{chord, description}] of live Hyprland binds, without omafind's own.
  property var binds: []
  property bool bindsReady: false
  property string bindsError: ""
```

Replace `function checkBindings(chords) { ... }` with:

```qml
  function getBinds() {
    bindsReady = false
    bindsError = ""
    if (!send({t: "binds_get"})) bindsError = "omafindd is not running, so the shortcut cannot be checked against your Hyprland bindings."
  }
```

In `receive` add:

```qml
    case "binds":
      binds = Array.isArray(message.binds) ? message.binds : []
      bindsReady = true
      break
```

In `receiveSetupError` add a branch before the final `else`:

```qml
    } else if (message.for === "binds_get") {
      bindsError = reason
```

Delete the `Component { id: bindingProcess ... }` block and its comment.

- [ ] **Step 4: Create `ui/ShortcutRow.qml` and `ui/ShortcutRecorder.qml`**

`ui/ShortcutRow.qml`:

```qml
import QtQuick
import qs.Commons
import ".." as Plugin

// The key recorder row (ported from omaone): the chord as key caps, or "Press a shortcut" with
// an accent border while recording, a note, and Change, which becomes Cancel. While recording
// the button keeps the keyboard and reports every key except Tab through captured().
Item {
  id: root
  objectName: "omafindShortcutRow"

  property var parts: []
  property string prompt: "Press a shortcut"
  property bool recording: false
  property bool canChange: true
  property string note: ""
  // "warn" draws the note in yellow, anything else dim.
  property string noteTone: ""

  signal change()
  signal cancel()
  signal captured(int key, int modifiers)

  function take() {
    button.forceActiveFocus()
  }

  function press() {
    if (recording) cancel()
    else if (canChange) change()
  }

  implicitHeight: Style.space(28)

  Rectangle {
    id: keys
    anchors.verticalCenter: parent.verticalCenter
    width: root.recording ? promptLabel.implicitWidth + 2 * Style.space(10) : caps.implicitWidth
    height: Style.space(28)
    radius: Style.cornerRadius
    color: "transparent"
    border.width: root.recording ? 1 : 0
    border.color: Color.accent

    Row {
      id: caps
      visible: !root.recording
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(4)

      Repeater {
        model: root.parts
        delegate: SetupKey {
          required property string modelData
          text: modelData
          implicitHeight: Style.space(26)
          fontSize: Style.font.body
          padding: Style.space(8)
        }
      }
    }

    Label {
      id: promptLabel
      visible: root.recording
      anchors.centerIn: parent
      text: root.prompt
      color: Util.alpha(Color.foreground, 0.85)
      font.bold: true
    }
  }

  Label {
    anchors.left: keys.right
    anchors.leftMargin: Style.space(12)
    anchors.right: button.left
    anchors.rightMargin: Style.space(12)
    anchors.verticalCenter: parent.verticalCenter
    elide: Text.ElideRight
    text: root.note
    color: root.noteTone === "warn" ? Plugin.Palette.yellow : Plugin.Tokens.dim
  }

  // Not ActionButton: that one takes Space and Enter as presses, and a recording needs them as keys.
  Rectangle {
    id: button
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    enabled: root.recording || root.canChange
    opacity: enabled ? 1 : 0.45
    width: Math.max(Style.space(76), label.implicitWidth + 2 * Style.space(16))
    height: Style.space(28)
    radius: Style.cornerRadius
    color: mouse.containsMouse ? Style.hoverFill : "transparent"
    border.width: 1
    border.color: activeFocus ? Color.accent : Style.normalBorderColor
    activeFocusOnTab: enabled
    Accessible.role: Accessible.Button
    Accessible.name: root.recording ? "Cancel changing the shortcut" : "Change the shortcut, now " + root.parts.join(" ")
    Accessible.onPressAction: root.press()

    Keys.onPressed: event => {
      if (!root.recording) {
        if (event.key === Qt.Key_Space || event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
          root.press()
          event.accepted = true
        }
        return
      }
      if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab) return
      event.accepted = true
      if (!event.isAutoRepeat) root.captured(event.key, event.modifiers)
    }
    onActiveFocusChanged: if (!activeFocus && root.recording) root.cancel()

    Label {
      id: label
      anchors.centerIn: parent
      text: root.recording ? "Cancel" : "Change"
      color: Color.foreground
      font.pixelSize: Style.font.body
    }

    MouseArea {
      id: mouse
      anchors.fill: parent
      enabled: button.enabled
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: {
        button.forceActiveFocus()
        root.press()
      }
    }
  }
}
```

`ui/ShortcutRecorder.qml`:

```qml
import QtQuick
import Quickshell
import Quickshell.Io
import "../lib/keycombo.js" as Keycombo

// Holds Hyprland in the omafind-record submap while the shortcut row records, so bound chords
// reach the overlay instead of firing (ported from omaone's Shortcuts recorder). Polls the
// submap every second and stops after 30 s. A leave always follows an enter.
Item {
  id: recorder
  visible: false

  property var binds: ({})
  property bool active: false
  property string conflict: ""
  // Hyprland is outside the submap, so bound chords still fire.
  property bool exposed: false
  // Hyprland left the submap mid-recording.
  property bool lost: false
  property string nonce: ""
  property string operation: ""
  property bool pendingLeave: false
  property string accepted: ""
  property string polledNonce: ""

  signal recorded(string chord)

  Component.onDestruction: {
    if (nonce !== "") Quickshell.execDetached(Keycombo.recordCommand(nonce, true))
  }

  function start() {
    if (active) return
    active = true
    conflict = ""
    exposed = false
    lost = false
    advance()
    limit.restart()
  }

  function advance() {
    if (transition.running) return
    if (pendingLeave) {
      pendingLeave = false
      if (nonce !== "") {
        operation = "leave"
        transition.exec(Keycombo.recordCommand(nonce, true))
        return
      }
    }
    if (active && operation !== "entered") {
      nonce = Date.now().toString() + "-" + Math.random().toString(36).slice(2)
      operation = "enter"
      transition.exec(Keycombo.recordCommand(nonce, false))
    }
  }

  function finished(submap) {
    if (operation === "enter") {
      operation = "entered"
      exposed = submap !== "omafind-record"
    } else if (operation === "leave") {
      operation = ""
      nonce = ""
      // Hyprland is back in its default submap before the chord is used.
      if (accepted !== "") recorded(accepted)
      accepted = ""
    }
    advance()
  }

  function pollSubmap() {
    if (!active || operation !== "entered" || submapQuery.running) return
    polledNonce = nonce
    submapQuery.running = true
  }

  function checkSubmap(submap) {
    if (polledNonce !== nonce || !Keycombo.recordingSubmapLost(active ? "shortcut" : "", operation, submap)) return
    stop()
    lost = true
  }

  function stop() {
    if (!active) return
    active = false
    conflict = ""
    exposed = false
    limit.stop()
    pendingLeave = true
    advance()
  }

  function capture(key, modifiers) {
    if (!active) return
    var parts = Keycombo.comboFromQt(key, modifiers)
    if (parts === null) return
    if (parts === "cancel") {
      stop()
      return
    }
    var message = Keycombo.checkCombo(parts, binds)
    if (message) {
      conflict = message
      return
    }
    accepted = Keycombo.toHyprland(parts)
    stop()
  }

  Process {
    id: transition
    stdout: StdioCollector {
      id: enterOutput
      waitForEnd: true
    }
    onExited: (exitCode, exitStatus) => recorder.finished(enterOutput.text.trim())
  }

  Process {
    id: submapQuery
    command: ["hyprctl", "submap"]
    stdout: StdioCollector {
      id: submapOutput
      waitForEnd: true
    }
    onExited: (exitCode, exitStatus) => recorder.checkSubmap(submapOutput.text)
  }

  Timer {
    interval: 1000
    repeat: true
    running: recorder.active
    onTriggered: recorder.pollSubmap()
  }

  Timer {
    id: limit
    interval: 30000
    onTriggered: recorder.stop()
  }
}
```

- [ ] **Step 5: Use them in `ui/SetupIndex.qml`**

Add `import "../lib/keycombo.js" as Keycombo`. Replace lines 20-74 (from `readonly property var chords` through `onChecksChanged: pick()`) with:

```qml
  readonly property var progress: service ? service.progress : null
  readonly property var rates: service && service.discover ? service.discover.rates : null
  readonly property var head: Setup.indexHead(progress, rates)
  readonly property var problems: progress && progress.problems ? progress.problems : []
  // The problem list grows the panel instead of scrolling inside it, up to eight rows.
  readonly property real extraHeight: showList && problems.length ? list.height + Style.space(8) : 0
  readonly property var bindMap: service ? Keycombo.bindMap(service.binds) : ({})
  readonly property bool bindsKnown: !!service && (service.bindsReady || service.bindsError !== "")
  // The saved chord may be taken by a bind added since; the user must pick another first.
  readonly property string chosenConflict: service && service.bindsReady && chosen !== ""
    ? Keycombo.checkCombo(Keycombo.fromHyprland(chosen), bindMap) || "" : ""

  function begin() {
    saveError = ""
    chosen = service ? service.settings.shortcut : "SUPER + E"
    if (service) service.getBinds()
  }

  function focusFirst() {
    if (save.enabled) save.forceActiveFocus()
    else closeButton.forceActiveFocus()
  }

  function saveShortcut() {
    if (!service || saving) return
    saving = true
    saveError = ""
    service.saveShortcut(chosen, menuRow, (ok, errorLine) => {
      root.saving = false
      if (ok) root.searchRequested()
      else root.saveError = errorLine || ""
    })
  }
```

Replace the shortcut `Item` (lines 260-326, the one with the key caps, the spinner, "Checking your bindings" and the Change button) with:

```qml
    ShortcutRow {
      id: shortcutRow
      width: parent.width
      parts: Keycombo.fromHyprland(root.chosen)
      recording: recorder.active
      canChange: !!root.service && root.service.bindsReady
      note: recorder.conflict
        || (recorder.lost ? "Hyprland left recording mode, so omafind stopped recording. Press Change to try again." : "")
        || (recorder.exposed ? "Recording can trigger bound keys. Press Esc to cancel." : "")
        || root.chosenConflict
        || (root.service ? root.service.bindsError : "")
      noteTone: note !== "" ? "warn" : ""
      onChange: {
        recorder.start()
        shortcutRow.take()
      }
      onCancel: recorder.stop()
      onCaptured: (key, modifiers) => recorder.capture(key, modifiers)
    }

    ShortcutRecorder {
      id: recorder
      binds: root.bindMap
      onRecorded: chord => root.chosen = chord
    }
```

Change the save button's `enabled` (line 417) to:

```qml
          enabled: root.chosen !== "" && root.bindsKnown && root.chosenConflict === "" && !recorder.active && !root.saving
```

Add `recorder.stop()` as the first line of the `closeButton`'s `onClicked`, so closing never leaves Hyprland in the submap (the recorder's destruction handler covers the overlay closing).

- [ ] **Step 6: Run the checks**

Run: `scripts/qmllint.sh && node --test "tests/js/*.test.mjs" && uv run --project helper pytest -q tests/helper/test_qml_text.py`
Expected: exit 0; all pass.

- [ ] **Step 7: Commit**

```bash
git add ui/ShortcutRow.qml ui/ShortcutRecorder.qml ui/SetupIndex.qml Service.qml lib/setup.js tests/js/setup.test.mjs
git commit -m "feat(setup): record the overlay shortcut instead of cycling three chords"
```

---

### Task 17: Host check on a capped dev daemon

No code changes and no commit. The screenshots and timings go to `~/.local/share/omafind/cache/refinements/` (not `/tmp`, which a reboot clears) and their summary goes into the pull request body.

**Files:**
- Create (outside the repo): `$S/home/...` fake home, `$S/shims/*`, `$S/shell/shell.qml`, `$S/timing.py`, where `S=~/.local/share/omafind/cache/refinements/scratch`.

**Interfaces:**
- Consumes: everything from Tasks 1 to 16. The daemon entry `python -m omafindd`, its socket `$XDG_RUNTIME_DIR/omafind/ui.sock`, `Service.qml` reading `$HOME/.config/omarchy/shell.json`.
- Produces: `folders.png`, `folders-expanded.png`, `shortcut.png`, `progress.png`, `preview-image.png`, `preview-pdf.png`, `timing.txt` in `~/.local/share/omafind/cache/refinements/`.

Rules for this task: one heavy job at a time, inside a capped scope. Never call `ShortcutRecorder.start()` in the harness, because it moves the live Hyprland into the `omafind-record` submap. Never send keys with `wtype`. Kill every process you start by PID. Leave `omafind.service` and `~/.config` alone.

- [ ] **Step 1: Build the fake home**

```bash
S=~/.local/share/omafind/cache/refinements/scratch
mkdir -p $S/home/Documents/notes $S/home/Pictures/clips $S/home/code/demo/.git $S/home/.config/omarchy $S/data/omafind
printf 'XDG_DOCUMENTS_DIR="$HOME/Documents"\nXDG_PICTURES_DIR="$HOME/Pictures"\n' > $S/home/.config/user-dirs.dirs
echo '{}' > $S/home/.config/omarchy/shell.json
for i in $(seq 1 40); do printf 'Meeting notes %s\nThe budget line is on line 2.\n' $i > $S/home/Documents/notes/note-$i.md; done
magick -size 64x64 xc:steelblue $S/home/Pictures/photo.png
for i in $(seq -w 1 300); do cp $S/home/Pictures/photo.png $S/home/Pictures/clips/clip_$i.png; done
pdf=$(find /usr/share/doc -name "*.pdf" -size -2M 2>/dev/null | head -1); [ -n "$pdf" ] && cp "$pdf" $S/home/Documents/; ls $S/home/Documents/*.pdf
ln -sfn ~/.local/share/omafind/runtime $S/data/omafind/runtime
ln -sfn ~/.local/share/omafind/model $S/data/omafind/model
```

Expected: at least one PDF listed. When none exists, write one with `magick -size 600x840 xc:white -pointsize 24 -annotate +40+80 'Budget' $S/home/Documents/budget.pdf`.

- [ ] **Step 2: Write the PATH shims**

```bash
mkdir -p $S/shims
for name in uwsm-app omarchy-launch-editor omarchy-launch-browser mpv xdg-open nautilus; do
  printf '#!/bin/sh\necho "%s $*" >> %s/launch.log\n' "$name" "$S" > $S/shims/$name
done
cat > $S/shims/systemctl <<'EOF'
#!/bin/sh
case "$*" in
  *is-enabled*omafind.service*) echo enabled ;;
  *is-active*omafind.service*) echo active ;;
  *) echo "systemctl shim refused: $*" >&2; exit 1 ;;
esac
EOF
chmod +x $S/shims/*
```

- [ ] **Step 3: Start the capped dev daemon**

```bash
mkdir -p /run/user/1000/ofdev && chmod 700 /run/user/1000/ofdev
systemd-run --user --scope --quiet --collect -p MemoryMax=8G -p MemorySwapMax=0 -- \
  env XDG_RUNTIME_DIR=/run/user/1000/ofdev HOME=$S/home XDG_DATA_HOME=$S/data \
  PYTHONPATH=$PWD/helper PATH=$S/shims:$PATH \
  ~/.local/share/omafind/venv/bin/python -m omafindd > $S/daemon.log 2>&1 &
echo $! > $S/daemon.pid
```

Run (after a second): `ls /run/user/1000/ofdev/omafind/ui.sock && tail -5 $S/daemon.log`
Expected: the socket exists and the log has no traceback.

- [ ] **Step 4: Write the offscreen harness**

```bash
mkdir -p $S/shell
ln -sfn /usr/share/omarchy/shell/Commons $S/shell/Commons
ln -sfn $PWD $S/shell/plugin
```

`$S/shell/shell.qml` (the `shot` property picks the screen; each run saves one PNG and quits):

```qml
import QtQuick
import Quickshell
import "plugin" as Plugin
import "plugin/ui" as Parts

ShellRoot {
  id: shell
  readonly property string shot: Quickshell.env("OF_SHOT")
  readonly property string out: Quickshell.env("OF_OUT")

  Plugin.Service {
    id: service
    pluginDir: Quickshell.env("OF_PLUGIN")
  }

  FloatingWindow {
    implicitWidth: 1200
    implicitHeight: 1000
    color: "black"

    Plugin.SetupView {
      id: setup
      visible: shell.shot === "folders" || shell.shot === "expanded" || shell.shot === "shortcut"
      anchors.fill: parent
      service: service
    }

    Plugin.SearchView {
      id: search
      visible: shell.shot === "progress"
      anchors.fill: parent
      service: service
    }

    Parts.PreviewLayer {
      id: preview
      visible: shell.shot === "image" || shell.shot === "pdf"
      width: 600
      height: 420
    }
  }

  // Depth-first search of the visual tree; the harness reaches inner items without new objectNames.
  function find(item, test) {
    if (test(item)) return item
    for (var i = 0; i < item.children.length; i++) {
      var hit = find(item.children[i], test)
      if (hit) return hit
    }
    return null
  }

  Timer {
    interval: 500
    running: true
    onTriggered: {
      if (shell.shot === "folders" || shell.shot === "expanded" || shell.shot === "shortcut") setup.reset()
      if (shell.shot === "shortcut") {
        // Step 3 shows once progress exists. The recorder never starts: that would switch the live Hyprland submap.
        service.progress = JSON.parse(Quickshell.env("OF_PROGRESS"))
        var row = shell.find(setup, item => item.objectName === "omafindShortcutRow")
        row.recording = true
        row.note = "Super Ctrl H is already bound to Hardware menu in Hyprland. Press another shortcut."
        row.noteTone = "warn"
      }
      if (shell.shot === "progress") {
        service.progress = JSON.parse(Quickshell.env("OF_PROGRESS"))
        search.progressOpen = true
      }
      if (shell.shot === "image") preview.source = "file://" + Quickshell.env("OF_IMAGE")
      if (shell.shot === "pdf") preview.source = "file://" + Quickshell.env("OF_PDF_PAGE")
      grab.start()
    }
  }

  Timer {
    id: expand
    interval: 1500
    running: shell.shot === "expanded"
    onTriggered: {
      var tree = shell.find(setup, item => typeof item.toggle === "function" && typeof item.indexOf === "function")
      tree.toggle(tree.indexOf(Quickshell.env("HOME") + "/Pictures"))
    }
  }

  Timer {
    id: grab
    interval: shell.shot === "folders" || shell.shot === "expanded" ? 3000 : 1000
    onTriggered: {
      var target = shell.shot === "image" || shell.shot === "pdf" ? preview
        : shell.shot === "progress" ? search : setup
      target.grabToImage(result => {
        result.saveToFile(shell.out)
        Qt.quit()
      })
    }
  }
}
```

The `expand` timer opens `~/Pictures` through `FolderTree.toggle(index)` (Task 12) after the first rows load.

- [ ] **Step 5: Take the screenshots**

```bash
R=~/.local/share/omafind/cache/refinements
shot() {
  systemd-run --user --scope --quiet --collect -p MemoryMax=8G -p MemorySwapMax=0 -- \
    env QT_QPA_PLATFORM=offscreen XDG_RUNTIME_DIR=/run/user/1000/ofdev HOME=$S/home PATH=$S/shims:$PATH \
    OF_PLUGIN=$PWD OF_SHOT=$1 OF_OUT=$R/$2 OF_PROGRESS="$(cat tests/fixtures/setup/progress.json)" \
    OF_IMAGE=$S/home/Pictures/photo.png OF_PDF_PAGE="$OF_PDF_PAGE" \
    quickshell -p $S/shell/shell.qml > $R/$1.log 2>&1
}
shot folders folders.png
shot expanded folders-expanded.png
shot shortcut shortcut.png
shot progress progress.png
shot image preview-image.png
```

For the PDF page, render it through the daemon's own code first:

```bash
OF_PDF_PAGE=$(HOME=$S/home XDG_DATA_HOME=$S/data uv run --project helper python -c \
  "import sys; from omafindd import preview; print(preview.render({'id': 1, 'kind': 'pdf', 'path': sys.argv[1], 'loc': 1})['image'])" \
  "$(ls $S/home/Documents/*.pdf | head -1)")
shot pdf preview-pdf.png
```

Run: `grep -nE "unavailable|Invalid|Cannot read|TypeError|ReferenceError" $R/*.log`
Expected: no output.

Read each PNG and check:
- `folders.png`: rows read `~/Documents`, `~/Pictures`, `~/code`; Documents and Pictures checked; counts or dim placeholders with a row spinner; header `folders 3 · scanning` or `scanned in 0.x s`; footer `selected … files · index … · time … · device …`. No "NOT INDEXED" and no section labels.
- `folders-expanded.png`: `Pictures` expanded shows `clips` indented, unchecked, with a `dataset` tag and `images 300 · named 100%`.
- `shortcut.png`: "Press a shortcut" with an accent border, "Cancel" button, the yellow conflict sentence.
- `progress.png`: the popover titled "Indexing" above the footer with five kind rows.
- `preview-image.png`, `preview-pdf.png`: sharp edges, the PDF page fills the 600x420 box width.
- All text crisp, no text smaller than 11 px except bold uppercase headers.

- [ ] **Step 6: Open at the matched line**

```bash
uv run --project helper python - <<'EOF'
import json, socket
s = socket.socket(socket.AF_UNIX)
s.connect("/run/user/1000/ofdev/omafind/ui.sock")
s.sendall((json.dumps({"t": "open", "path": "/dev/null", "line": 2}) + "\n").encode())
print(s.recv(4096))
EOF
cat $S/launch.log
```

Expected: `launch.log` has an `omarchy-launch-editor +2 …` line, or the reply names why `/dev/null` cannot open. When it refuses `/dev/null`, repeat with an indexed note path from the fake home after an `index_start` from the harness, and confirm `+2`.

- [ ] **Step 7: First paint and expand time on the real `$HOME`**

`$S/timing.py` reads names only, so it is light and runs without the daemon:

```python
import sys
import time
from pathlib import Path

from omafindd import discovery

home = Path.home()
started = time.monotonic()
rows = discovery.top(home=home)
paint = time.monotonic() - started
started = time.monotonic()
first = next((row for row in rows if row["hasChildren"]), None)
kids = discovery.children(Path(first["path"])) if first else []
expand = time.monotonic() - started
walk = discovery.Walk(home)
started = time.monotonic()
walk.run()
total = time.monotonic() - started
print(f"top rows {len(rows)} · paint {paint * 1000:.0f} ms · expand {expand * 1000:.0f} ms ({len(kids)} rows) · walk {total:.1f} s")
sys.exit(0)
```

Run: `systemd-run --user --scope --quiet --collect -p MemoryMax=8G -p MemorySwapMax=0 -- uv run --project helper python $S/timing.py | tee ~/.local/share/omafind/cache/refinements/timing.txt`
Expected: paint and expand each under 100 ms; the walk prints its seconds.

- [ ] **Step 8: Run the full suites once more**

Run: `uv run --project helper pytest -q && node --test "tests/js/*.test.mjs" && scripts/qmllint.sh && uv run --project helper ruff check helper tests bin/omafind scripts`
Expected: all pass, exit 0.

- [ ] **Step 9: Stop everything**

```bash
kill $(cat $S/daemon.pid)
pgrep -x llama-server; pgrep -af "python -m omafindd"
```

Expected: `pgrep -x llama-server` prints nothing. The second command prints only the live `omafind.service` daemon, whose PID matches `systemctl --user show omafind.service -p MainPID`. Kill any leftover dev process by its PID.

---

## Self-review

**Spec coverage.**
- A1 lazy discovery and IPC: Tasks 8 and 9 (`top`, `Walk`, `children`, `discover_counts`, `discover_children`, `docs/ipc.md`). `discover_tree` and `candidates` removed in Tasks 9 and 13.
- A2 leave-out rules: Task 7 (media-only dataset, camera and ISO-date names, `keep` without the dataset drop) and Task 13 (`leftout.py` gone).
- A3 selection model: Task 10.
- A4 list and rows: Tasks 11, 12, 13 (cache, `ListView`, row layout, dataset evidence, header and footer facts, ledger removed, drive dialog moved).
- B shortcut capture: Tasks 14 (`binds_get`, lone F-keys), 15 (`keycombo.js`), 16 (row, recorder, Save rules, hard-coded chords removed).
- C1 sharp text: Task 1. C2 progress popover and `index_progress`: Task 5. C3 keys: Task 2. C4 previews: Task 4. C5 open at line: Task 3. C6 smaller fixes: Task 6.
- Testing: pytest and node items sit in the owning tasks; the host check is Task 17.

**Placeholder scan.** No TBD or TODO. Task 12 no longer points at Task 17 for its smoke run; the host check lives only in Task 17.

**Type consistency.**
- `tree.js` keeps `chosen` and `skipped` on a `choices` object; QML holds it as `choices`, never `state`, which every `Item` already has.
- `Service.children[path]` is `{dirs, volume, error}` everywhere (Tasks 11, 12, 13).
- `SetupService._discovery` is the one task set Tasks 9 and 14 add to and stop.
- `binds_get` items are `{chord, description}` with chord labels like `Super Ctrl H`, the same form `Keycombo.label` produces, so `bindMap` keys match `checkCombo` lookups.
- `ShortcutRecorder.recorded(chord)` carries the Hyprland form (`SUPER + H`) that `Service.saveShortcut` and `valid_shortcut` accept.

**Review Focus coverage.** Each line names its test: walk failure (Task 9 `test_walk_failure_ends_with_done_and_error`, Task 12 `walkError`), a repeated `discover_start` (Task 9 `test_repeat_discover_start_reuses_walk_and_replays_counts`), unreadable and symlinked folders (Task 8 `test_folders_hide_symlinks_hidden_heavy_and_secrets`, `test_children_of_unreadable_folder_report_error`), a wide `$HOME` (Task 8 `test_top_caps_rows_at_limit`), Ctrl+C with a query selection and Esc with the popover open (Tasks 2 and 5).
