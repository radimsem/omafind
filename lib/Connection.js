.pragma library

function initial() {
  return {unit: "unknown", socket: "closed", failures: 0}
}

function reduce(state, event) {
  var next = {unit: state.unit, socket: state.socket, failures: state.failures}
  switch (event.type) {
  case "unit":
    next.unit = event.enabled ? "enabled" : "missing"
    break
  case "socket-open":
    next.socket = "open"
    break
  case "state":
    next.socket = "ready"
    next.failures = 0
    break
  case "attempt-failed":
    next.socket = "closed"
    next.failures += 1
    break
  }
  return next
}
