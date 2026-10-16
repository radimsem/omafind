.pragma library
.import "format.js" as Format

var F = typeof Format !== "undefined" ? Format : this
var K = {Key_Escape: 0x01000000, Key_Return: 0x01000004, Key_Enter: 0x01000005,
  Key_Up: 0x01000013, Key_Down: 0x01000015, Key_PageUp: 0x01000016, Key_PageDown: 0x01000017,
  Key_Home: 0x01000010, Key_End: 0x01000011, Key_Space: 0x20, Key_J: 0x4a,
  Key_K: 0x4b, Key_C: 0x43, Key_Comma: 0x2c, Key_I: 0x49, Key_N: 0x4e, Key_P: 0x50, ControlModifier: 0x04000000,
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
  if (ctrl && key === K.Key_I) return "progress"
  if (ctrl && key === K.Key_Comma) return "settings"
  var row = ctx.row
  if (!row) return null
  var enter = key === K.Key_Return || key === K.Key_Enter
  if (row.type === "weak") return enter && !ctrl ? "toggle-weak" : null
  if (row.type !== "item") return null
  var item = row.item
  // A selection in the query is the field's to copy.
  if (ctrl && key === K.Key_C) return ctx.selection ? null : "copy"
  if (item.offline) return null
  if (enter) return ctrl ? "reveal" : "open"
  if (ctrl && key === K.Key_Space && (item.kind === "audio" || item.kind === "video")) return "play"
  return null
}

function hints(row, jump) {
  var close = {keys: ["Esc"], label: "close"}
  if (!row || row.type === "header") return [close]
  if (row.type === "weak") return [{keys: ["Enter"], label: row.expanded ? "collapse" : "expand"}, close]
  var copy = {keys: ["Ctrl", "C"], label: "copy path"}
  var item = row.item
  if (item.offline) return [copy, close]
  var line = jump != null ? jump : item.loc
  var target = F.at(item)
  if (item.kind === "text" && line != null) target = "L" + line
  var open = "open"
  if (target) {
    if (item.kind === "pdf") open += " at page " + item.loc
    else if (item.kind === "text") open += " at line " + line
    else open += " at " + target
  }
  var result = [{keys: ["Enter"], label: open}, {keys: ["Ctrl", "Enter"], label: "show in folder"}]
  if (item.kind === "audio" || item.kind === "video") result.push({keys: ["Ctrl", "Space"], label: "play at " + target})
  return result.concat([copy, close])
}

// The footer with no query: progress while an index runs, then Settings and close.
function idleHints(progress) {
  var result = progress ? [{keys: ["Ctrl", "I"], label: "progress"}] : []
  return result.concat([{keys: ["Ctrl", ","], label: "settings"}, {keys: ["Esc"], label: "close"}])
}

function editorName(raw) {
  var name = raw.split("/").pop()
  var known = {nvim: "Neovim", vim: "Vim", hx: "Helix", emacs: "Emacs", zed: "Zed", code: "VS Code"}
  return known[name] || name.charAt(0).toUpperCase() + name.slice(1)
}

function actionLabel(item, editorName, jump) {
  var line = jump != null ? jump : item.loc
  var target = F.at(item)
  if (item.kind === "text" && line != null) target = "L" + line
  if (!target) return "Open"
  if (item.kind === "pdf") return "Open at page " + item.loc
  if (item.kind === "text") return "Open in " + editorName + " at line " + line
  return "Open at " + target
}
