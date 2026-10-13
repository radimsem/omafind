.pragma library

function initial() {
  return {id: null, playing: false, position: 0, start: 0}
}

function reduce(state, event) {
  var next = {id: state.id, playing: state.playing, position: state.position, start: state.start}
  var command = null
  switch (event.type) {
  case "toggle":
    if (state.id !== event.item.id) {
      var start = event.item.loc == null ? 0 : event.item.loc
      next = {id: event.item.id, playing: true, position: start, start: start}
      command = {op: "start", path: event.item.path, start: start}
    } else {
      next.playing = !state.playing
      command = {op: next.playing ? "resume" : "pause"}
    }
    break
  case "selection":
    if (state.id != null && state.id !== event.id) {
      next = initial()
      command = {op: "stop"}
    }
    break
  case "position":
    next.position = event.seconds
    break
  case "ended":
    next = initial()
    break
  }
  return {state: next, command: command}
}

function mpvArgs(path, start, socketPath) {
  return ["mpv", "--no-video", "--no-terminal", "--start=" + start,
    "--input-ipc-server=" + socketPath, "--", path]
}
