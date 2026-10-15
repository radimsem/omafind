# omafind design

This is the approved design for omafind in one place. The canvas is the source of truth. This file records its tokens, components, keys and copy rules so an implementation can match it one to one. When this file and the canvas disagree, the canvas wins and this file gets fixed.

- Published canvas: https://claude.ai/artifact/VPwvi2kmd8oRpCqmdjUAXt (private to the owner)
- Board sources: `docs/design/canvas/<Board>.dc.html` for markup, copy and `renderVals()` logic
- Styles and tokens: `docs/design/canvas/omafind.css` (omafind parts) on top of `docs/design/canvas/omaone.css` (shared shell tokens)
- Board order and titles: `docs/design/canvas/canvas.json`
- Behavior spec: `docs/superpowers/specs/2026-10-11-omafind-design.md`, section 7 for the overlay, keys and jump map

Canvas title: "omafind desktop designs". Boards in canvas order, as `File: title`:

- Main: "1 · Image on top"
- Moments: "2 · Video moment on top"
- Audio: "3 · Audio moment on top"
- Typing: "4 · PDF page on top, while typing"
- Docs: "5 · Document on top"
- Code: "6 · Code on top (code: prefix)"
- Degraded: "7 · Keyword-only and offline drive"
- Empty: "8 · Opened, no query yet"
- Anatomy: "9 · Result states and keys"
- Setup: "10 · Setup 1: runtime and model"
- Discover: "11 · Setup 2: pick folders, with what is left out"
- Exclusions: "11b · Setup 2: leave out subfolders"
- Indexing: "12 · Setup 3: first index and shortcut"
- NewDrive: "13 · New drive plugged in"
- MotionSearch: "M1 · Motion: search as you type"
- MotionBrowse: "M2 · Motion: browse, preview and open moments"
- MotionSetup: "M3 · Motion: first run"
- MotionFresh: "M4 · Motion: new files and drives"

The Folders step follows `docs/superpowers/specs/2026-10-14-setup-and-search-refinements-design.md`. Its lazy tree replaces the Discover and Exclusions boards' older ledger and toolbar.

## Principles

- omafind looks like the Omarchy shell. It reads the current theme, follows the user's font and corner rounding, and adds no palette of its own. The canvas is rendered in Catppuccin, which is one Omarchy theme.
- Flat surfaces. A 2 px border, no shadow, no blur. Tone and borders separate parts.
- The accent means "this is the selection or the match". Yellow means a hit word, an offline drive, a dataset proposal or a degraded state. Red means a failure. Green means done, kept or protected.
- Square corners by default, as Omarchy is. Corners follow Hyprland `decoration:rounding` (0 by default, 8 on the author's machine).
- The overlay is summoned, never parked. It opens on an empty query and closes after Enter or Esc.
- Facts, not prose. omafind computes every status, so it shows the computed values as key/value tokens and keeps sentences for instructions, errors with a fix, and titles.
- Every action has a key. The footer lists the keys for the selected result and changes with it.
- Words answer first and meaning re-ranks. The list never jumps under the cursor: rows move by transform and the selection follows its row.

## Color

The canvas tokens live in `:root` of `omaone.css`. The plugin never holds a hex value. It reads `qs.Commons.Color`, `qs.Commons.Style` and `qs.Commons.Util` from the Omarchy shell (`/usr/share/omarchy/shell/Commons`). Mocha values below are for checking a screenshot against a board.

`Color` exposes five foundation properties: `foreground`, `background`, `accent`, `urgent` (the theme's `red` or `color1`) and `muted`. It also exposes surface groups: `popups`, `tooltip`, `notifications`, `menu` and `imagePicker`, each with `background`, `text`, `border` and some extra roles. `Util.alpha(color, opacity)` makes the alpha variants. `Style` exposes the control state fills and borders.

| Canvas token | Mocha | Meaning | Omarchy property |
|---|---|---|---|
| `--base` | `#1e1e2e` | Overlay fill, text on a filled button or accent chip | `Color.popups.background`, `Color.background` |
| `--mantle` | `#181825` | Code and text excerpt well, desktop behind the boards | `Color.menu.background`. Desktop is the user's wallpaper. |
| `--crust` | `#11111b` | Chip on a thumbnail (at 0.85), drive window well | `Util.alpha(Color.background, n)` with the same `n` |
| `--surface0` | `#313244` | Thumbnail well, player card, waveform well | none, derived: `Util.alpha(Color.foreground, 0.11)` over the overlay (computed from Mocha, check by screenshot) |
| `--fg` | `#cdd6f4` | Primary text, file names, hit words in a list row | `Color.foreground`, `Color.popups.text` |
| `--fg2` | `#b2bad4` | Secondary text, paths, snippets, key cap text | `Util.alpha(Color.foreground, 0.85)` |
| `--dim` | `#9298ae` | Captions, fact keys, folders, footer, badges at rest | `Util.alpha(Color.foreground, 0.66)` (the value `Color.lock.placeholder` defaults to) |
| `--placeholder` | `#808598` | Placeholder in the query field | `Util.alpha(Color.foreground, 0.55)` |
| `--muted` | `#585b70` | Line numbers in text and code excerpts | `Color.muted` |
| `--accent` | `#89b4fa` | Selected row, focus border, prefix, hit facts, progress, waveform match | `Color.accent` |
| `--red` | `#f38ba8` | Failures | `Color.urgent` |
| `--yellow` | `#f9e2af` | Hit words, offline, dataset tag | none, see below |
| `--green` | `#a6e3a1` | Done, kept, secrets rule, verified | none, see below |
| `--cyan` | `#94e2d5` | Image accents | none, see below |
| `--fill-normal` | fg at 0.04 | Idle control fill | `Style.normalFill` |
| `--fill-hover` | fg at 0.08 | Badge fill, icon well, progress track | `Style.hoverFill` |
| `--fill-selected` | fg at 0.18 | Chosen tile | `Style.selectedFill` |
| `--ctl-border` | fg at 0.40 | Control, checkbox, key cap and dashed outline | `Style.normalBorderColor` |
| `--sep` | fg at 0.12 | Hairlines, pane divider, unfocused border | `Util.alpha(Color.foreground, 0.12)` |
| selected row | accent at 0.22 plus 1 px accent inset | Selected result row (`.it.on`) | `Util.alpha(Color.accent, 0.22)`. `Style.selectedAccentFill` is 0.18, so the board and the token differ. |
| accent washes | accent at 0.06 to 0.20 | Included table row, mixed checkbox, active kind chip | `Util.alpha(Color.accent, n)` |
| scrim | base at 0.5 | Behind the overlay, below the bar | `Color.menu.scrim` |

The boards show no colored section icons. Section headers and result thumbnails stay in `--fg2` and `--dim` (see Open questions).

Surface roles:

| Canvas use | Omarchy property |
|---|---|
| Overlay surface border (`.surf.focus`, always focused) | `Color.popups.border` |
| Toast fill, text, border (`.ntf`, `.tst`) | `Color.notifications.background`, `.text`, `.border` |
| Hover and focus outlines | `Style.hoverBorderColor`, `Style.focusBorderColor` |
| Button hover | `Style.hoverFill` |

### Canvas colors with no Omarchy equivalent

`Color` does not expose `green`, `yellow` or `cyan`, and `Color.qml` ignores every `colors.toml` key except foreground, background, accent, muted, `color0`, `color4`, `color7`, `color8` and red. omafind needs yellow (hit words, offline, dataset tag), green (done, kept, secrets tag, verified) and cyan (image accents). The first issue that needs them adds `Palette.qml`, a singleton that reads `Color.currentThemePath + "/colors.toml"` for `green`, `yellow` and `cyan`, as omaone's does. The omafind plugin shares no state with omaone, so it carries its own copy. Omaone falls back to `Color.foreground` for green and to `Color.urgent` for yellow. The canvas gives no fallback for cyan: not found, decide it in the issue. That singleton is the only place these colors enter the plugin.

Other values with no theme token, derived in QML from the roles above:

- Caption chips on images and frames `rgba(17,17,27,.85)`: `Util.alpha(Color.background, 0.85)`. The player play button uses 0.78.
- Hit wash behind a word `rgba(249,226,175,.18)`: `Util.alpha(Palette.yellow, 0.18)`, text in `Palette.yellow`.
- Offline badge fill: `Palette.yellow` at 0.12. Done step fill: `Palette.green` at 0.16. Running step fill: accent at 0.12.
- Error card wash: `Color.urgent` at 0.08 for a failure, `Palette.yellow` at 0.08 for a degraded or paused state (`server-starting`, `index-running`, `embedding-unavailable`, `disk-low`, `update-running`). The glyph takes the same color. `tone()` in `lib/errors.js` maps the code to the tone; views never pick it.
- Rule tag borders: accent for repos, cyan for worktrees and yellow for datasets.
- Rendered PDF page `#e6e9ef` with text `#4c4f69`, and its hit highlight `rgba(223,142,29,.35)`: these draw page content, not shell chrome. They stay fixed in every theme.
- Placeholder image tints `#2c3a52`, `#3a3346`, `#2f3f3d`, `#403a33`, `#33364a`: mock photo content. The real thumbnail replaces them.
- Popup 0.97 alpha: `Color.popups.background` is opaque by default. Use the theme value. Do not force 0.97.

## Type

One family. The canvas names JetBrains Mono. The plugin binds `Style.font.family`, which follows the user's `omarchy font set` choice and resolves to JetBrainsMono Nerd Font on a stock install. Never hard-code the family.

Sizes follow `Style.font` (base size 12). Use the token, not the number.

| Canvas size | `Style.font` token | Use |
|---|---|---|
| 10 | `caption` | Bold uppercase section headers only |
| 11 | `bodySmall` | Table headers, badges, fact tokens, rule tags, key caps, folder line, footer, why line, meta, status, hints |
| 12 | `body` | Table rows, paths, buttons, preview path and meta, banners, toasts |
| 13 | `subtitle` | Result file name (700), task titles, empty-state hint text |
| 15 | none | Empty state headline |
| 16 | `heading` | Setup panel title (700) |
| 18 | `iconLarge` is the nearest, but it is an icon token | Preview file name (700) |
| 22 | none, `display` is 24 | Query text |
| 28 | `displayLarge` | Board titles only. Not in the product. |

Static text uses `ui/Label.qml` (native rendering). Letter spacing is rounded to whole pixels.

The sizes 15, 18 and 22 have no exact token. Pick the nearest and record it in the pull request.

Weights: 400 body, 700 for result file names, the preview name, the setup title, section headers, badges, tags and primary buttons. Section headers are uppercase with 0.1em tracking, table headers, the weaker-matches row and rule tags 0.08em. Numbers in tables use tabular figures. Line height is 30 for the query, 16 for snippets and 14 for fact tokens.

## Shape, border and spacing

Corners come from `Style.cornerRadius` (`--r` in the CSS). Square is 0 and rounded is 8. Circles stay circles in both: the 60 px play button on a video frame, the 46 px play button on the audio card, the spinner. The checkbox keeps a fixed 2 px radius.

Borders:

- The overlay and the setup panel: 2 px, accent (`.surf.focus`). The panel is always focused. A toast is also 2 px accent.
- Hairlines: 1 px `--sep` under the query row, between the panes, above the footer, under table headers.
- Controls (checkboxes, key caps, secondary buttons, rule tags): 1 px `--ctl-border`.
- Selected result row: accent at 0.22 and a 1 px accent inset ring. Focused table row: 1 px accent inset.
- No shadow anywhere.

Spacing (px, at base size 12):

| Part | Value |
|---|---|
| Search overlay | 1280 by 800, centered on the focused monitor and offset 13 below center so it sits under the 26 px bar |
| Query row | 68 high, 22 side padding, 14 gap, search icon 22 in accent |
| Two-pane split | List pane 470 wide with 10 padding and a 1 px right rule. Preview takes the rest (about 809). |
| Result row | 56 high, 44 thumbnail, columns 44, flexible, auto, 12 gap, 10 side padding, 2 between rows |
| Section header | 10 px bold, 12 above and 6 below, 30 high in the motion layout |
| Weaker-matches row | 36 high on the Code board (`.wk`), 10 side padding |
| Preview pane | Padding 26 top, 32 sides, 24 bottom, 18 gap. Media area 420 high |
| Preview media | Image 600 by 400, video frame 600 by 400, player card 600 by 340, PDF page 330 by 410, text and code well 640 by 400 |
| Preview actions | Buttons 32 high, 8 gap, 16 side padding on the primary |
| Footer | 40 high, 18 side padding, 16 gap, keys right-aligned |
| Setup panel | 1120 wide (760 for step 1, 920 for step 3), 18 padding, 14 gap |
| Setup panel sizes in M3 | 760 by 474, 1120 by 992, 920 by 574 |
| Folder table columns | 28, flexible, 64, 56, 64, 56, 56, 84, 72, 32 with a 10 gap and 10 side padding |
| Table header | 30 high |
| Table row | 44 high in the shared lazy folder tree |
| Toast | 380 wide, 12 and 14 padding, at the top right, 36 below the top and 10 from the edge |
| Kind progress row | Columns 80, flexible, 190 with a 14 gap, 6 px bar |
| Progress bar | 120 by 4 in the footer, 6 high in setup |

The 16 px values on the boards:

- Rule tag (`.tg`): 16 high, 5 side padding, 4 gap, 11 px uppercase.
- Checkbox (`.cb`): 16 square, 1.5 px border, check glyph 11 px.
- Side padding of the footer row and the banner (`.of-f`, `.ban`): 16.
- The gap between footer items in the search overlay: 16.

## Motion

The easing is `cubic-bezier(0.33, 1, 0.68, 1)` unless a row says `ease` or `linear`. No bounce, no blur, no spring.

| Motion | Duration and curve | Where |
|---|---|---|
| Summon | 160 ms in, 120 ms out. Opacity and an 8 px rise from below. | Overlay (M1, M2) |
| Scrim | 140 ms in, 120 ms out | Behind the overlay |
| Keyword leg | Shows 50 ms after the last keystroke | M1 |
| Meaning leg | Re-ranks after 200 ms without typing | M1 |
| Re-rank | Rows move by transform over 220 ms. Opacity 160 ms. Rows that appear stagger 20 ms each. | M1 |
| Selection | 100 ms on background and inset ring | Result rows, table rows, checkboxes |
| Preview cross-fade | 120 ms opacity. The media area rises 6 px over 120 ms (160 ms in). | M1, M2 |
| Empty to results | 140 ms opacity, results delayed 30 ms | M1 |
| Open | Overlay closes, then the opener window fades in over 250 ms | M2 |
| Toast | 180 ms in from 12 px right and 12 px up, stays 2.8 s. An error toast with a fix stays until Retry or Dismiss. | M1, M2, M4 |
| Progress | 300 ms linear on width, 200 ms on color | M3, M4 |
| Setup panel resize | 240 ms on width and height | M3 |
| Setup step swap | Out 120 ms, in 160 ms after a 120 ms delay | M3 |
| Step and task state | 160 ms on color, border and fill | M3 |
| New file in results | 240 ms fade, "new" tag stays 2.8 s | M4 |
| Play position | 100 ms linear on width and playhead | M2 |
| Waveform bars in window | 640 ms alternate pulse, scale 1 to 0.8 | M2 |
| Spinner | 0.9 s linear | Query row status |
| Caret blink | 1.1 s `steps(1)` (1.06 s on M4) | Query field |
| Key press flash | 160 to 170 ms | Board key strips |

With motion off (`motion: still` on the boards) nothing animates and the spinner shows a fixed arc.

## Components

Each row names the class in `omafind.css` and the boards where it appears.

| Component | Class | Properties | Boards |
|---|---|---|---|
| Search overlay | `.sp`, `.sp-q`, `.sp-main`, `.sp-f` | Surface, 1280 by 800. Query row, list pane, preview pane, footer. | Main to Empty, Anatomy, M1, M2, M4 |
| Query row | `.sp-q`, `.q`, `.pref`, `.st` | Search icon (a code icon with `code:`). Query at 22, prefix in accent, status on the right at 11 ("ready", "38 ms", "matching by meaning" with a spinner). | every search board |
| Result row | `.it`, `.th`, `.tx`, `.nm`, `.dir`, `.bd` | See below. | every search board |
| Section header | `.sec-h`, `.n`, `.more` | Uppercase name, count, and "2 more" aligned right in dim. | Main, Moments, Audio, Docs, Code |
| Weaker-matches fold | `.wk`, `.sp-weak`, `.ln` | A chevron row "5 weaker matches" (Code) or a caption with a hairline (Anatomy). Hits under half the top score fold into it. Enter expands them. | Code, Anatomy |
| Preview, image | `.pv-img` | Picture fitted, `ts` chip top right. | Main, M1, M4 |
| Preview, video | `.pv-img`, `.play`, `.scrub`, `.tl-track` | Matched frame, 60 px play button, timestamp chip, scrubber with match markers (3 by 14, best marker yellow 4 by 18). | Moments, M2 |
| Preview, audio | `.pcard`, `.wf`, `.pbtn`, `.trk`, `.capt` | Player card with waveform, 46 px accent play button, progress bar with the matched window in accent, caption "7:55 – 8:25 of 13:43". | Audio, M2 |
| Preview, PDF | `.pv-page`, `.pg` | Rendered page, hit words highlighted, page chip bottom left. | Typing, M1, M2 |
| Preview, text | `.pv-text`, `.l`, `.no`, `.hit`, `.chip` | Excerpt with line numbers in `--muted`, hit lines at accent 0.10, hit words in yellow, line-range chip bottom right. | Docs, M1, M2 |
| Preview, code | `.pv-text`, `.chip` | Same well as text, with a code icon in the query row. | Code |
| Preview info | `.pv-name`, `.pv-path`, `.pv-meta` | Name at 18 bold, folder at 12, meta line `Kind · date · size facts` in dim. | every search board |
| Why line | `.pv-why`, `.fx`, `.f`, `.k`, `.v` | See Why line below. | every search board |
| Preview actions | `.pv-act`, `.btn-acc`, `.btn-sec` | Primary in accent fill with base text, "Show in folder" secondary. Offline: "Open" disabled and "Copy path". | every search board |
| Footer | `.sp-f` | Result count left ("17 results · 3 weaker"), key hints right. With no query: indexing progress, watched folders, offline drives. | every search board |
| Banner | `.ban`, `.act` | A thin wrapper around `ErrorCard` for the fact-token form (the disk banner). Yellow wash at 0.08, glyph, bold lead, fact tokens. | Degraded |
| Error card | `ErrorCard` (`.ban` anatomy) | Glyph, bold title, detail wrapped and capped at three lines, buttons right: "Install packages" (install fix), "Open log" (log), "Retry" (a retry or install fix, only where the view has no retry control of its own; step 1 uses its footer). An install fix adds `sudo pacman -S --needed <packages>` in mono with "Copy", and shows "Installing in the terminal" next to the still pressable "Install packages" while it waits for the packages. The open toast adds "Dismiss" under the card. Red wash for a failure, yellow for a degraded or paused state. The compact form (preview pane, open toast) drops the pacman line and caps the detail at two lines. Shows nothing when its error is null. | Degraded. Not drawn on the setup, preview and toast boards. |
| Empty state | `.empty`, `.hints`, `.hint` | Headline, one sentence, prefix chips (`img:`, `pdf:`, `doc:`, `vid:`, `aud:`, `code:`) with the prefix in accent. | Empty, M1 |
| Steps | `.steps`, `.step`, `.no`, `.dash` | 20 px number box, done in green wash, current in accent. | Setup to Indexing, M3 |
| Lazy folder tree | `FolderTree`, `FolderTable`, `FolderRow` | Check, disclosure, path, repo or dataset tag, five kind counts, index size, time, and code toggle. One ListView shared by setup and the drive dialog. | Folders step, NewDrive |
| Task row | `.task`, `.mk`, `.t`, `.d`, `.v` | 22 px marker (ok in green wash, running in accent wash, waiting in a 1 px outline), title 13 bold, detail 11 dim, value right. | Setup, M3 |
| Kind progress | `.kp`, `.bar2` | Name, 6 px bar (accent, green when done), count text right. | Indexing, M3 |
| Toast | `.ntf`, `.tst`, `.h`, `.b`, `.a` | Surface with accent border, glyph and bold title, body, buttons right. | NewDrive, M1, M2, M4 |
| Drive dialog | `.of`, `.p-head`, `.tag`, `.dt` | Title with fact line, "removable" tag, folder table, watch facts, totals, "Cancel" and "Index this drive". | NewDrive, M4 |

### Result row

- Thumbnail or kind icon in a 44 px well. Name at 13 bold, folder at 11 dim, badge right.
- Selected: accent fill and ring, and the folder turns `--fg2`. Enter acts on this row. The top hit is selected on every new result set.
- Keyword hit: the snippet with the typed words in bold replaces the folder. In M1 the words fade to bold as they are typed.
- Badge shows the jump target: `14:32`, `p. 12`, `L41`, `L1–47`. A partly indexed PDF shows `30 of 412` with `queued p. 31–412` as a fact token.
- Offline: name and thumbnail at 0.7 opacity, folder reads `Photos2024 · /2019/lisbon`, badge `offline` in yellow on its wash.
- Weak: name and snippet at 0.6 opacity on the overlay rows (`.r.dimmed`).

### Why line

- A row of fact tokens: dim key, value, 14 gap, 11 px. Values are `--fg2`, a hit is accent, a warning is yellow, an emphasized value is `--fg` bold.
- Keys in order: `leg`, `part`, `at`, `hits`, `z`. A PDF or text hit adds the quoted snippet under it, led by an `Aa` glyph.
- Examples: `leg meaning · part image · z 3.4`, `leg meaning · part frame + speech · at 14:32 · z 3.1`, `leg words · part text · at p. 12 · hits they`, `leg meaning + words · part code · at L1–47 · hits retry, backoff · z 2.9`.

### Lazy folder tree

- One flat ListView model contains the visible rows. Expanding requests one level and caches it in Service; collapsing removes visible descendants while retaining their cache and expansion state. Adding a folder or rescanning preserves expanded paths that still exist.
- Rows show a tri-state checkbox, disclosure chevron, name and tag, then Text, PDF, Images, Video, Audio, Index, and Time. A repo also has a code toggle. Top rows use `~/name`; deeper rows use the basename. Indent is 18 per level with a 1 px guide at 0.24.
- On is accent fill with a base-colored check, mixed is an accent wash with an accent dash, and off is an empty outline. A checked row has an accent wash at 0.06. Checking a parent searches its descendants; unchecking a child creates an exclude for that path.
- Unknown counts show dim placeholders and one row spinner. A finished or failed walk stops its spinners. Failures show a reason and a next step, without a scan-time fact.
- XDG folders start checked. Other home folders and extra volume rows start unchecked. Dataset proposals under searched parents start unchecked unless the user already chose them. A yellow `dataset` tag has evidence such as `images 1,418 · named 96%`; checking it queues its files normally.
- The header shows `folders <n> · scanning`, then `scanned in <s> s` on success. The footer shows `selected <files> files · index <size> · time <t> · device <gpu>` for the searched paths. Add folder sits below the tree.

## Keyboard model

Global (Hyprland, an owned block in the bindings written by setup):

| Key | Action |
|---|---|
| `Super E` | Open or close omafind (default of the `shortcut` setting). Setup offers `Super D` or `Super U` when it is taken. |

In the overlay:

| Key | Applies | Action |
|---|---|---|
| Typing | Query | The words leg answers after 50 ms. The meaning leg re-ranks after 200 ms without typing. |
| `img:` `pdf:` `doc:` `vid:` `aud:` `code:` | Start of query | Limit the search to one kind. The prefix stays in the row in accent. `code:` searches the code index only. |
| `↑` `↓` or `Ctrl J` `Ctrl K` | Any | Move across sections. |
| `Enter` | Result | Open at the match. |
| `Enter` | Weaker-matches row | Expand the folded hits. |
| `Ctrl Enter` | Result | Show in folder. |
| `Ctrl Space` | Audio or video | Play or pause the preview from the matched second. Other kinds show no hint. |
| `Ctrl C` | Result | Copy the path. |
| `Esc` | Any | Clear the query, then close. |
| Click a row | Any | Select it. |

Offline results disable `Enter` and show only `Ctrl C` and `Esc` in the footer.

What Enter opens:

| Kind | Opener |
|---|---|
| PDF | Default browser at `#page=N` through `omarchy-launch-browser` |
| Video, audio | `mpv --start=<seconds>` |
| Image | `xdg-open` |
| Text, code | The `editor` setting at the line, in a terminal |

Footer hint text follows the selection: "open at 14:32", "open at page 1", "open at line 212", "open in Neovim at line 8", "play at 7:55", "preview".

Setup:

| Key | Applies | Action |
|---|---|---|
| `Right` / `Left` | Folder tree | Expand / collapse the focused folder. |
| `Space` | Folder checkbox | Toggle the folder. |
| `Esc` | Empty state | Close. |

Setup buttons, by step: "Install", "Pause" while it runs, "Retry" after a failure or "Resume" when paused, then "Next: pick folders"; "Back" and "Start indexing"; "Close" and "Save shortcut and open search"; "Not this drive" and "Scan"; "Cancel" and "Index this drive". The Setup board shows only "Pause"; the other step 1 labels come from the error handling spec. The boards define no other setup key (see Open questions).

## Copy

Every string comes verbatim from the boards. A string the canvas lacks follows these rules, and the pull request lists it for review.

- Sentence case, straight quotes, serial comma. No exclamation marks, no emoji, no bold inside copy.
- No em or en dashes in prose. Use a comma, a colon, a period or parentheses. A dash used as a placeholder glyph, a range inside a fact token (`L1–47`, `7:55–8:25`) or the separator inside a composed label is typography and stays. The middle dot in `Photos2024 · /2019/lisbon` and in meta lines is the separator.
- Terse and technical. A label or subtitle can be a fragment. A banner, toast or error is a full sentence.
- A control says what it does ("Open", "Show in folder", "Copy path", "Retry", "Scan", "Index this drive"). A state is one word or a fact ("ready", "offline", "new").
- An error says what happened, why, and what to do next, in that order. The title says what happened. The detail says why, then what to do next, and names a control ("press Retry"), never a CLI command. Example: title "The embedding server did not start.", detail "It did not answer within 60 s. Showing keyword matches until it starts.", with a "Retry" button. The daemon writes error copy in `helper/omafindd/errors.py`; the plugin writes only `daemon-offline` and `unknown` in `lib/errors.js`, and `update-running` and `update-failed` in `lib/Update.js` (see `docs/ipc.md`, Errors).
- Avoid seamless, leverage, robust, comprehensive, delve, showcase, vibrant, crucial, pivotal, streamline, empower, foster, testament, landscape, tapestry, journey, unlock and elevate.

### Facts, not prose

Any line that explains a result, a scan or a skip is a row of fact tokens: a dim key, a value, nothing else. No verb, no article.

| Where | Keys, in order |
|---|---|
| Why line of a result | `leg` (`meaning`, `words`, `meaning + words`), `part` (`image`, `ocr`, `frame`, `speech`, `audio`, `text`, `code`; the boards also join them as `frame + speech`), `at`, `hits`, `z` |
| Folder tree rows | Five kind counts; dataset evidence uses `images`, `videos`, or `audio`, then `named` (percent). Errors use `error`. |
| Progress and totals | `selected`, `index`, `time`, `device`, `vram`, `skipped`, `failed`, `queued` |

Keys the boards use that spec 7.4 does not list: `dataset`, `searchable`, `mount`, `fs`, `scan`, `watch`, `reconcile`, `source`, `deletes`, `opener`, `path`, `roots`, `volumes`, `read`, `tracked`, `dot`, `heavy`, `got`, `left`, `disk`, `verify`, `repo`, `quant`, `license`, `backend`, `gpu`, `unit`, `venv`, `vram idle`. Add them to the spec's table when the spec is next edited.

What stays a sentence:

- Titles: "Set up omafind", "Pick the folders to search", "Indexing your files", "New drive found".
- Instructions: "Type a description in any language. Start with a prefix to search one kind only.", "Install builds the server (about 3 min) and downloads the model (865 MB)." and "You can close this. Installing keeps going."
- Errors with a fix: "Photos2024 is not connected." with "Connect it, then press Retry."
- Prompts: "Photos2024 (exFAT, 1.8 TB) is connected. Scan it for photos, videos and documents to search?"
- Setup explanation: "omafind writes its own block in your Hyprland bindings and reloads Hyprland. Nothing else in your config changes."
- Toasts: a short sentence, or a title plus fact tokens (`Opening <name>` with `opener` and `at`).

Name things as the spec does: result, section, weaker matches, volume, drive, root, left out, index. A drive result reads `Label · /path`.

## Building it in QML

- Theme only through `qs.Commons.Color`, `qs.Commons.Style` and `qs.Commons.Util`, plus `Palette.qml` for green, yellow and cyan. No hex literal in any `.qml` file. The rendered PDF page colors are the one exception and belong in the thumbnail item, not in chrome.
- Reuse `qs.Ui` where it matches, as omaone does, and style any piece it lacks from the tokens above.
- Corner radius, gaps, font and spacing come from `Style`. Do not copy the pixel values in this file into code when a token covers them. The overlay size, the 470 px list pane and the row heights have no token and live as named constants.
- Result grouping, the fact-token formatter, the jump target badge and the reducer for the two legs live in `.pragma library` JS files under `lib/` and run under `node --test`.
- The list is one flat model moved by transform, not rebuilt, so the re-rank animates (M1). Responses carry a sequence id and older ones are dropped.
- Check each surface by screenshot (`grim`) beside its board before calling it done.

## Open questions

- Esc: Anatomy and spec 7.1 say it clears the query, then closes. M1 and M2 close the overlay at once with results showing. This file follows Anatomy.
- `Super E`: Anatomy says "Open or close". In M2 the key only reopens a closed overlay and does nothing while it is open. M1 shows it only as a hint chip. This file follows Anatomy.
- Badge and open line: Docs shows `L212` (one line) and opens "at line 212" while the chip says `lines 205–222`. Code shows `L1–47` (a range), its button reads "Open in Neovim" with no line, and its footer says "at line 8". Spec 7.1 expects `Open in <editor> at line 8`. Text and code badges differ in kind.
- Weaker matches: Anatomy and spec fold them into one row. Main and M1 count them in the footer ("3 weaker", "2 weaker") but show no fold row, and M1 leaves them in the list at 0.6 opacity. Code uses a different fold row (`.wk`) from Anatomy (`.sp-weak`).
- Open toast: M1 shows "Opened <name>", a sentence. M2 shows "Opening <name>" with `opener` and `at` tokens. Spec 7.4 favors the second.
- New drive toast: spec 4.4 reads "New drive Photos2024 found. Scan it for content?". The boards read "New drive found" with a longer body. The canvas wins.
- `Ctrl Space`: audio and video play from the matched second. The footer shows the hint only for audio and video.
- Section icons: the brief expects kind colors on section icons. The boards color only the composition bar and its legend. The fallback color for cyan is also undefined.
- Folder tree keys: Tab moves between controls, Space toggles a checkbox or code action, and Right and Left expand and collapse the focused folder.
- Type sizes 15, 18 and 22 have no exact `Style.font` token.
- Why line `hits`: spec 7.1 omits `hits` on the text row while the Docs board shows `hits picked, vulkan, cuda`. Spec 7.4 appears before 7.3 in the file.
