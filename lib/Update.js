.pragma library

// `local` is the build of the loaded plugin, `daemon` the build in the last `state` ("" from a
// daemon that predates the field). A daemon that crashes on start sends no `state`, so a `venv`
// event from `bin/omafind status --json` can also start setup. Setup runs at most once per local
// build, so a failing setup never loops; only `retry` runs it again.
function initial() {
  return {local: null, daemon: null, phase: "idle", tried: null, error: "", failure: null}
}

function reduce(state, event) {
  var next = {local: state.local, daemon: state.daemon, phase: state.phase, tried: state.tried,
    error: state.error, failure: state.failure || null}
  var effects = []
  switch (event.type) {
  case "local":
    next.local = event.build
    break
  case "venv":
    if (event.state !== "stale" && event.state !== "missing") return {state: next, effects: effects}
    break
  case "daemon":
    next.daemon = event.build
    if (next.phase === "failed" && next.daemon === next.local) {
      next.phase = "idle"
      next.error = ""
      next.failure = null
    }
    break
  case "setup-exited":
    if (state.phase !== "updating") return {state: next, effects: effects}
    next.phase = event.ok ? "idle" : "failed"
    next.error = event.ok ? "" : event.line || "bin/omafind setup failed"
    next.failure = event.ok ? null : event.error || null
    return {state: next, effects: effects}
  case "retry":
    if (state.phase === "failed") {
      next.phase = "updating"
      next.error = ""
      next.failure = null
      effects.push({type: "setup"})
    }
    return {state: next, effects: effects}
  }
  var behind = event.type === "venv" || (next.daemon !== null && next.daemon !== next.local)
  if (next.phase !== "updating" && next.local && behind && next.tried !== next.local) {
    next.phase = "updating"
    next.tried = next.local
    next.error = ""
    next.failure = null
    effects.push({type: "setup"})
  }
  return {state: next, effects: effects}
}

// The search banner for an update as an error object, or null. No daemon is there to write the
// copy while omafindd restarts, so the codes are the plugin's own.
function banner(state) {
  if (state.phase === "updating")
    return {code: "update-running", title: "omafindd is updating to match the installed plugin.",
      detail: "Search returns when it restarts."}
  if (state.phase === "failed") {
    if (state.failure) {
      var failure = state.failure
      var error = {code: "update-failed", title: "omafindd did not update.",
        detail: (failure.title + " " + failure.detail).trim(),
        fix: failure.fix && failure.fix.kind === "install" ? failure.fix : {kind: "retry"}}
      if (failure.log) error.log = failure.log
      return error
    }
    return {code: "update-failed", title: "omafindd did not update.",
      detail: state.error.replace(/\.$/, "") + ". Press Retry to try again.", fix: {kind: "retry"}}
  }
  return null
}
