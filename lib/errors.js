.pragma library

// Degraded and paused states that recover by themselves; every other code is a failure.
var WARN_CODES = ["server-starting", "embedding-unavailable", "disk-low", "index-running", "update-running"]

// An error object passes through. An older daemon's bare `reason` string becomes an `unknown` error.
function wrap(value) {
  if (value && typeof value === "object") return value
  if (typeof value === "string" && value.trim() !== "") return {code: "unknown", title: value.trim(), detail: ""}
  return null
}

// The error a daemon message carries: a `t:"error"` reply with the fields beside `t`, `for`, `seq` or
// `id`, an `error` field, or an older daemon's bare `reason`. Routing fields are left out.
function from(message) {
  if (!message || typeof message !== "object") return wrap(message)
  if (message.error !== undefined && message.error !== null) return from(message.error)
  if (typeof message.title !== "string") return wrap(message.reason)
  var error = {code: message.code || "unknown", title: message.title, detail: message.detail || ""}
  if (message.fix) error.fix = message.fix
  if (message.log) error.log = message.log
  return error
}

function tone(code) {
  return WARN_CODES.indexOf(code) >= 0 ? "warn" : "urgent"
}

function hasInstall(error) {
  return !!(error && error.fix && error.fix.kind === "install" && Array.isArray(error.fix.packages)
    && error.fix.packages.length > 0
    && error.fix.packages.every(function(pkg) { return /^[a-z0-9@._+-]+$/.test(pkg) }))
}

function hasRetry(error) {
  return !!(error && error.fix && error.fix.kind === "retry")
}

// The line to paste instead of pressing Install packages.
function installCommand(fix) {
  return hasInstall({fix: fix}) ? "sudo pacman -S --needed " + fix.packages.join(" ") : ""
}

// The socket did not answer. `logPath` is the daemon's startup log when that file exists.
// engineError also holds runtime build errors from the daemon; only a failed bin/omafind setup
// explains why the service is down.
function setupFailure(error) {
  return error && (error.code === "helper-install-failed" || error.code === "tools-missing") ? error : null
}

function offline(logPath) {
  return {code: "daemon-offline", title: "The omafind service is not running.",
    detail: "It did not answer on its socket. Press Retry to start it.", fix: {kind: "retry"},
    log: logPath || undefined}
}
