# Settings

omafind keeps its settings inline on the `radimsem.omafind` entry in `~/.config/omarchy/shell.json`. The defaults below come from [`settings.example.json`](../settings.example.json).

| Key | Type | Default |
|---|---|---|
| `setupDone` | bool | `false` |
| `gpu` | `"auto"` or `"never"` | `"auto"` |
| `audio` | bool | `true` |
| `roots` | `[{path, volume, excludes: [path]}]` | `[]` |
| `ignoredVolumes` | list of filesystem UUIDs the new-drive toast skips | `[]` |
| `imageBudget` | 70, 140 or 280 | `140` |
| `maxResults` | int, clamped to 10..200 | `40` |
| `warmMinutes` | int, clamped to 0..60 | `5` |
| `shortcut` | uppercase `MODS + KEY` (mods: SUPER, SHIFT, CTRL, ALT) or a lone `F1` to `F35` | `"SUPER + E"` |

An invalid value falls back to its default. A `codeRoots` key left by an older plugin is ignored and dropped on the next save.

## Change settings

Press `Ctrl ,` in the overlay to open Settings. It changes the shortcut (checked against your Hyprland binds), shows or hides the Find files row in the Omarchy menu, and opens setup at the Folders step through Change folders. Setup writes `roots` and `setupDone`.

The plugin writes settings through `updateEntryInline`. The daemon only reads them and picks up a change without a restart.
