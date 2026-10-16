.pragma library
.import "errors.js" as Errors

// QML supplies import namespaces; the Node loader shares one global context.
var E = typeof Errors !== "undefined" ? Errors : this

// `discover` and `driveDiscover` are the latest home and drive discover_result. `walks` maps a walk
// root to {done, seconds, error, failure} from its latest batch; `discoverCounts` maps a folder to
// its rolled-up counts; `datasets`, `repos` and `worktrees` map a folder to what the walks found.
// `childFolders` caches discover_children replies as {dirs, volume, error}, and `childrenAsked`
// holds the paths still waiting for one.
function initial() {
  return {discover: null, driveDiscover: null, scanning: false, driveScanning: false, walks: {},
    discoverCounts: {}, datasets: {}, repos: {}, worktrees: {}, childFolders: {}, childrenAsked: {}}
}

// Commands carry `online`, whether the socket can take a message now. Effects are
// {type: "send", message}, {type: "error", surface, error} for the folderError or driveError
// surface, and {type: "children", path} once a children reply is cached. A map that an event does
// not touch keeps its identity, so QML bindings on it do not fire.
function reduce(state, event) {
  var next = Object.assign({}, state)
  var effects = []
  var message = event.message
  switch (event.type) {
  case "scan":
    effects.push({type: "error", surface: "folderError", error: null})
    next.scanning = !!event.online
    if (event.online) effects.push({type: "send", message: {t: "discover_start"}})
    break
  case "scan-drive":
    effects.push({type: "error", surface: "driveError", error: null})
    next.driveDiscover = null
    next.driveScanning = !!event.online
    if (event.online) effects.push({type: "send", message: {t: "discover_start", volume: event.uuid}})
    break
  case "children":
    var cached = state.childFolders[event.path]
    if ((cached && !cached.error) || state.childrenAsked[event.path] || !event.online) return {state: state, effects: effects}
    next.childrenAsked = Object.assign({}, state.childrenAsked)
    next.childrenAsked[event.path] = true
    effects.push({type: "send", message: {t: "discover_children", path: event.path}})
    break
  case "stop":
    next.scanning = false
    next.driveScanning = false
    // The daemon answers children requests still in flight with `discover_stop`.
    next.childrenAsked = {}
    next.walks = {}
    for (var path in state.walks) next.walks[path] = Object.assign({}, state.walks[path], {done: true})
    if (event.online) effects.push({type: "send", message: {t: "discover_stop"}})
    break
  case "offline":
    next.scanning = false
    next.driveScanning = false
    next.childrenAsked = {}
    next.walks = Object.assign({}, state.walks)
    var failure = E.offline()
    for (var walkRoot in next.walks) if (!next.walks[walkRoot].done)
      next.walks[walkRoot] = {done: true, seconds: null, error: failure.title, failure: failure}
    break
  case "failed":
    if (event.for === "discover_start") {
      if (state.driveScanning) next.driveScanning = false
      else next.scanning = false
    } else if (event.for === "discover_children") {
      next.childrenAsked = {}
    } else {
      return {state: state, effects: effects}
    }
    break
  case "discover_result":
    if (Array.isArray(message.roots)) message.roots.forEach(function(entry) { clear(next, entry.path) })
    if (message.volume) {
      next.driveScanning = false
      next.driveDiscover = message
      effects.push({type: "error", surface: "driveError", error: null})
    } else {
      next.scanning = false
      next.discover = message
      effects.push({type: "error", surface: "folderError", error: null})
    }
    break
  case "discover_counts":
    if (typeof message.root !== "string" || !message.counts) return {state: state, effects: effects}
    receiveCounts(next, message, effects)
    break
  case "discover_children":
    receiveChildren(next, message)
    effects.push({type: "children", path: message.path})
    break
  default:
    return {state: state, effects: effects}
  }
  return {state: next, effects: effects}
}

function under(path, root) { return path === root || path.indexOf(root.replace(/\/$/, "") + "/") === 0 }

// Clears counts, datasets and walks under `walkRoot`. Cached children stay: they hold the folder
// lists and the volume of folders added outside every root. A drive mounted inside the root has
// its own walk, and its snapshot may already have arrived, so its subtree stays.
function clear(next, walkRoot) {
  var nested = Object.keys(next.walks).filter(function(root) { return root !== walkRoot && under(root, walkRoot) })
  function outside(path) { return !under(path, walkRoot) || nested.some(function(root) { return under(path, root) }) }
  // The folders step sorts when a walk finishes, so a rescan must not inherit the old finish.
  var fields = ["discoverCounts", "datasets", "repos", "worktrees", "walks"]
  fields.forEach(function(field) {
    var kept = Object.assign({}, next[field])
    for (var path in kept) if (!outside(path)) delete kept[path]
    next[field] = kept
  })
}

// Walks and folder rows show a failure as one fact: the error's title.
function errorText(value) {
  var error = E.wrap(value)
  return error ? error.title : ""
}

function receiveCounts(next, message, effects) {
  if (message.reset) clear(next, message.root)
  next.discoverCounts = Object.assign({}, next.discoverCounts)
  for (var path in message.counts) next.discoverCounts[path] = message.counts[path]
  var roots = (next.driveDiscover && Array.isArray(next.driveDiscover.roots) ? next.driveDiscover.roots : [])
    .concat(next.discover && Array.isArray(next.discover.roots) ? next.discover.roots : [])
  var scanRoot = roots.find(function(entry) { return entry.path === message.root }) || next.childFolders[message.root]
  var driveWalk = scanRoot ? !!scanRoot.volume : next.driveScanning
  if (message.error && !driveWalk) effects.push({type: "error", surface: "folderError", error: E.wrap(message.error)})
  if (Array.isArray(message.datasets)) {
    next.datasets = Object.assign({}, next.datasets)
    message.datasets.forEach(function(entry) { next.datasets[entry.path] = entry })
  }
  if (Array.isArray(message.worktrees)) {
    next.worktrees = Object.assign({}, next.worktrees)
    message.worktrees.forEach(function(path) { next.worktrees[path] = {path: path} })
  }
  if (Array.isArray(message.repos)) {
    next.repos = Object.assign({}, next.repos)
    message.repos.forEach(function(path) { next.repos[path] = {path: path} })
  }
  next.walks = Object.assign({}, next.walks)
  // `error` is the title, one fact in folder rows; `failure` keeps the object for the drive dialog.
  next.walks[message.root] = {done: !!message.done, seconds: typeof message.seconds === "number" ? message.seconds : null,
    error: errorText(message.error), failure: E.wrap(message.error)}
}

function receiveChildren(next, message) {
  var dirs = Array.isArray(message.dirs) ? message.dirs : []
  next.childFolders = Object.assign({}, next.childFolders)
  next.childFolders[message.path] = {dirs: dirs, volume: typeof message.volume === "string" ? message.volume : "",
    error: errorText(message.error)}
  next.discoverCounts = Object.assign({}, next.discoverCounts)
  next.datasets = Object.assign({}, next.datasets)
  next.repos = Object.assign({}, next.repos)
  next.worktrees = Object.assign({}, next.worktrees)
  dirs.forEach(function(dir) {
    // A streamed batch is newer than the snapshot inside a children reply.
    if (dir.counts && !next.discoverCounts[dir.path]) next.discoverCounts[dir.path] = dir.counts
    if (dir.evidence) next.datasets[dir.path] = Object.assign({path: dir.path}, dir.evidence)
    if (dir.repo) next.repos[dir.path] = {path: dir.path}
    if (dir.worktree) next.worktrees[dir.path] = {path: dir.path}
  })
  next.childrenAsked = Object.assign({}, next.childrenAsked)
  delete next.childrenAsked[message.path]
}
