.pragma library

// Ported from omaone/lib/keycombo.js; capture uses the omafind-record submap.
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
  if (parts[0] !== "Super" && !(parts.length === 1 && FUNCTION_KEY.test(parts[0]))) {
    return name + " would fire while you type. Add Super and try again."
  }
  return bindConflict(parts, binds)
}

// The sentence for a chord Hyprland already binds, or null.
function bindConflict(parts, binds) {
  var name = label(parts)
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
    + "  submap=$(hyprctl submap 2>/dev/null) || exit 1\n"
    + "  if [ \"$submap\" = omafind-record ]; then\n"
    + "    hyprctl dispatch 'hl.dsp.submap(\"reset\")' >/dev/null 2>&1 || exit 1\n"
    + "    submap=$(hyprctl submap 2>/dev/null) || exit 1\n"
    + "    [ \"$submap\" != omafind-record ] || exit 1\n"
    + "  fi\n  rm -f \"$record\"\nfi\n"
  if (leave) {
    // A destroyed recorder can queue cleanup before its enter script reaches the lock.
    return ["sh", "-c", lock
      + "if [ \"$(cat \"$record\" 2>/dev/null)\" != \"$1\" ]; then : > \"$record.$1.cancel\"; fi\n"
      + cleanup, "omafind-record", nonce]
  }
  // Fixed crash backstop: it must still restore keys if QML can no longer run its idle timer.
  var watchdog = "sleep 31\n" + lock + cleanup + "rm -f \"$record.$1.cancel\"\n"
  return ["sh", "-c", lock
    + "if [ -e \"$record.$1.cancel\" ]; then rm -f \"$record.$1.cancel\"; exit 0; fi\n"
    + "printf '%s\\n' \"$1\" > \"$record\" || exit 1\n"
    // Closing fd 9 keeps the detached watchdog from retaining the enter script's lock.
    + "setsid -f sh -c '" + watchdog.replace(/'/g, "'\\''") + "' omafind-watchdog \"$1\" 9>&- >/dev/null 2>&1\n"
    + "if ! hyprctl binds -j 2>/dev/null | jq -e 'any(.[]; .submap == \"omafind-record\" and (.key // \"\" | ascii_upcase) == \"ESCAPE\" and .modmask == 64)' >/dev/null 2>&1; then\n"
    + "  hyprctl eval 'hl.define_submap(\"omafind-record\", function() hl.bind(\"SUPER + F24\", hl.dsp.no_op()); hl.bind(\"SUPER + ESCAPE\", hl.dsp.submap(\"reset\"), { non_consuming = true }) end)' >/dev/null 2>&1 || exit 1\n"
    + "fi\n"
    + "hyprctl binds -j 2>/dev/null | jq -e 'any(.[]; .submap == \"omafind-record\" and (.key // \"\" | ascii_upcase) == \"ESCAPE\" and .modmask == 64)' >/dev/null 2>&1 || exit 1\n"
    + "hyprctl dispatch 'hl.dsp.submap(\"omafind-record\")' >/dev/null 2>&1\n"
    + "hyprctl submap 2>/dev/null", "omafind-record", nonce]
}
