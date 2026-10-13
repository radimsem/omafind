.pragma library
.import "format.js" as Format

var F = typeof Format !== "undefined" ? Format : this
var K = {Key_Escape: 0x01000000, Key_Return: 0x01000004, Key_Enter: 0x01000005,
  Key_Up: 0x01000013, Key_Down: 0x01000015, Key_Space: 0x20, Key_J: 0x4a,
  Key_K: 0x4b, Key_C: 0x43, ControlModifier: 0x04000000,
  AltModifier: 0x08000000, ShiftModifier: 0x02000000}

function action(event, ctx) {
  var key = event.key
  var ctrl = (event.modifiers & K.ControlModifier) !== 0
  var alt = (event.modifiers & K.AltModifier) !== 0
  if (key === K.Key_Escape) return ctx.query ? "clear" : "close"
  if (key === K.Key_Up || ((ctrl || alt) && key === K.Key_K)) return "up"
  if (key === K.Key_Down || ((ctrl || alt) && key === K.Key_J)) return "down"
  var row = ctx.row
  if (!row) return null
  var enter = key === K.Key_Return || key === K.Key_Enter
  if (row.type === "weak") return enter && !ctrl ? "expand" : null
  if (row.type !== "item") return null
  var item = row.item
  if (ctrl && key === K.Key_C) return "copy"
  if (item.offline) return null
  if (enter) return ctrl ? "reveal" : "open"
  if (ctrl && key === K.Key_Space && (item.kind === "audio" || item.kind === "video")) return "play"
  return null
}

function hints(row, jump) {
  var close = {keys: ["Esc"], label: "close", dim: false}
  if (!row || row.type === "header") return [close]
  if (row.type === "weak") return [{keys: ["Enter"], label: "expand", dim: false}, close]
  var copy = {keys: ["Ctrl", "C"], label: "copy path", dim: false}
  var item = row.item
  if (item.offline) return [copy, close]
  var line = jump != null ? jump
    : item.kind === "code" && item.open_line != null ? item.open_line : item.loc
  var target = F.at(item)
  if ((item.kind === "text" || item.kind === "code") && line != null) target = "L" + line
  var open = "open"
  if (target) {
    if (item.kind === "pdf") open += " at page " + item.loc
    else if (item.kind === "text" || item.kind === "code") {
      open += " at line " + line
    } else open += " at " + target
  }
  var playable = item.kind === "audio" || item.kind === "video"
  return [{keys: ["Enter"], label: open, dim: false},
    {keys: ["Ctrl", "Enter"], label: "show in folder", dim: false},
    {keys: ["Ctrl", "Space"], label: playable ? "play at " + target : "preview", dim: !playable},
    copy, close]
}

function editorName(raw) {
  var name = raw.split("/").pop()
  var known = {nvim: "Neovim", vim: "Vim", hx: "Helix", emacs: "Emacs", zed: "Zed", code: "VS Code"}
  return known[name] || name.charAt(0).toUpperCase() + name.slice(1)
}

function actionLabel(item, editorName, jump) {
  var line = jump != null ? jump
    : item.kind === "code" && item.open_line != null ? item.open_line : item.loc
  var target = F.at(item)
  if ((item.kind === "text" || item.kind === "code") && line != null) target = "L" + line
  if (!target) return "Open"
  if (item.kind === "pdf") return "Open at page " + item.loc
  if (item.kind === "text" || item.kind === "code") {
    return "Open in " + editorName + " at line " + line
  }
  return "Open at " + target
}
