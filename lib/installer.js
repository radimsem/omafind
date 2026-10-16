.pragma library

// Package installs run in Omarchy's floating terminal, a normal window that always stacks
// under the overlay's layer surface. The overlay stands aside from launch until that terminal
// closes. `terminals` counts open windows with the terminal's app id.

function initial() {
  return {aside: false, seen: false, before: 0}
}

function reduce(state, event) {
  switch (event.type) {
  case "launch":
    return {aside: true, seen: false, before: event.terminals}
  case "terminals":
    if (!state.aside) return state
    if (event.terminals > state.before) return {aside: true, seen: true, before: state.before}
    return state.seen ? initial() : state
  case "timeout":
    return state.aside && !state.seen ? initial() : state
  case "end":
    return initial()
  }
  return state
}
