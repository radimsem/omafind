.pragma library

// The Folders step selection: absolute paths in `chosen` and `skipped`, and repo folders whose
// code is indexed in `code`. The nearest choice at or above a folder decides it.
var KINDS = ["text", "pdf", "image", "video", "audio"]

function isInside(path, folder) {
  return folder === "" || path === folder || path.indexOf(folder.replace(/\/$/, "") + "/") === 0
}

function parent(path) {
  var index = path.lastIndexOf("/")
  return index < 0 ? "" : path.slice(0, index)
}

function make(chosen, skipped, code) {
  return {chosen: chosen, skipped: skipped, code: code}
}

function initial(folders) {
  return make(folders.filter(function(folder) { return folder.xdg }).map(function(folder) { return folder.path }), [], [])
}

// The choice that decides `path`: {path, on}, or {path: null, on: false} with none above it.
function owner(path, state) {
  var best = {path: null, on: false}
  function consider(list, on) {
    list.forEach(function(folder) {
      if (isInside(path, folder) && (best.path === null || folder.length > best.path.length)) best = {path: folder, on: on}
    })
  }
  consider(state.chosen, true)
  consider(state.skipped, false)
  return best
}

function searched(path, state) {
  return owner(path, state).on
}

function mark(path, state) {
  var on = searched(path, state)
  var differs = (on ? state.skipped : state.chosen).some(function(folder) {
    return folder !== path && isInside(folder, path)
  })
  return differs ? "mixed" : on ? "on" : "off"
}

function sameSet(a, b) {
  return a.length === b.length && a.every(function(folder) { return b.indexOf(folder) >= 0 })
}

function settle(state, path, on, defaults) {
  function outside(folder) { return !isInside(folder, path) }
  var next = make(state.chosen.filter(outside), state.skipped.filter(outside), state.code)
  if (searched(path, next) !== on) (on ? next.chosen : next.skipped).push(path)
  if (!on) return next
  ;(defaults || []).slice().sort(function(a, b) { return a.length - b.length }).forEach(function(folder) {
    if (folder !== path && isInside(folder, path) && searched(folder, next)) next.skipped.push(folder)
  })
  return next
}

// Sets `path` and clears every choice below it. Turning a folder on leaves out the `defaults`
// below it (known worktrees and datasets) again. A folder mixed only through those defaults
// would not change, so the click turns it off instead. Repos left unsearched lose their code.
function click(state, path, defaults) {
  var on = mark(path, state) === "mixed" || !searched(path, state)
  var next = settle(state, path, on, defaults)
  if (on && sameSet(next.chosen, state.chosen) && sameSet(next.skipped, state.skipped))
    next = settle(state, path, false)
  next.code = next.code.filter(function(repo) { return !isInside(repo, path) || searched(repo, next) })
  return next
}

function toggleCode(state, path) {
  var code = state.code.indexOf(path) >= 0
    ? state.code.filter(function(folder) { return folder !== path }) : state.code.concat([path])
  return make(state.chosen, state.skipped, code)
}

// A dataset under a searched folder starts left out. `proposed` lists datasets already offered,
// so one the user checked is not skipped again when a later walk reports it.
function addDatasets(state, datasets, proposed) {
  var skipped = state.skipped.slice()
  datasets.forEach(function(dataset) {
    if (proposed.indexOf(dataset.path) >= 0) return
    var decided = owner(dataset.path, state)
    if (decided.on && decided.path !== dataset.path) skipped.push(dataset.path)
  })
  return make(state.chosen, skipped, state.code)
}

// Choices and mounts strictly below `path` with no other one between them and `path`.
function innermost(path, state, mounts) {
  var below = state.chosen.concat(state.skipped, mounts || []).filter(function(folder, index, all) {
    return folder !== path && isInside(folder, path) && all.indexOf(folder) === index
  })
  return below.filter(function(folder) {
    return !below.some(function(other) { return other !== folder && isInside(folder, other) })
  })
}

// Whether the code index takes code files in `path`: it is searched and the nearest repo at or
// above it has code on. `repos` lists every known repo, so a submodule decides for itself.
function codeOn(path, state, repos) {
  if (!searched(path, state)) return false
  var nearest = null
  ;(repos || []).concat(state.code).forEach(function(repo) {
    if (isInside(path, repo) && (nearest === null || repo.length > nearest.length)) nearest = repo
  })
  return nearest !== null && state.code.indexOf(nearest) >= 0
}

// Searched files under `path` per kind, plus `code`. Outside the innermost choices and repos
// everything follows `path`'s own state, so each one swaps its subtree's share for its own
// value. `mounts` are drives mounted below a walked root: that walk stays on its filesystem, so
// their files only add to `path`.
function value(path, state, countOf, mounts, repos) {
  var counts = countOf(path)
  if (!counts) return null
  var on = searched(path, state)
  var code = codeOn(path, state, repos)
  var result = {}
  KINDS.forEach(function(kind) { result[kind] = on ? counts[kind] || 0 : 0 })
  result.code = code ? counts.code || 0 : 0
  var inner = innermost(path, state, (mounts || []).concat(repos || [], state.code))
  for (var i = 0; i < inner.length; i++) {
    var sub = countOf(inner[i])
    var kept = value(inner[i], state, countOf, mounts, repos)
    if (!sub || !kept) return null
    var walked = (mounts || []).indexOf(inner[i]) < 0
    KINDS.forEach(function(kind) { result[kind] += kept[kind] - (on && walked ? sub[kind] || 0 : 0) })
    result.code += kept.code - (code && walked ? sub.code || 0 : 0)
  }
  return result
}

// Roots to index. A searched mount below a root becomes a root of its own, since the root's
// walk does not cross into it.
function toRoots(chosen, skipped, volumeOf, mounts) {
  var folders = chosen.filter(function(path, index) {
    if (chosen.indexOf(path) !== index) return false
    var outer = chosen.filter(function(folder) { return folder !== path && isInside(path, folder) })
    return !outer.some(function(folder) {
      return !skipped.some(function(skip) { return isInside(path, skip) && isInside(skip, folder) && skip !== folder })
    })
  })
  ;(mounts || []).forEach(function(mount) {
    if (folders.indexOf(mount) < 0 && searched(mount, make(chosen, skipped, []))) folders.push(mount)
  })
  return folders.map(function(path) {
    return {path: path, volume: volumeOf(path), excludes: skipped.filter(function(skip, index) {
      return skip !== path && isInside(skip, path) && skipped.indexOf(skip) === index
    }).map(function(skip) { return skip.slice(path === "/" ? 1 : path.replace(/\/$/, "").length + 1) })}
  })
}

function total(counts) {
  return counts ? KINDS.reduce(function(sum, kind) { return sum + (counts[kind] || 0) }, 0) : null
}

// Largest first. A folder the walk has not reached sits between those with files and those
// without, so it does not jump far when its count lands.
function byCount(rows, countOf) {
  function rank(row) {
    var value = total(countOf(row.path))
    return value === null ? 1 : value > 0 ? 0 : 2
  }
  return rows.slice().sort(function(a, b) {
    var ra = rank(a), rb = rank(b)
    if (ra !== rb) return ra - rb
    if (ra === 0) {
      var diff = total(countOf(b.path)) - total(countOf(a.path))
      if (diff) return diff
    }
    var na = (a.name || a.path).toLowerCase(), nb = (b.name || b.path).toLowerCase()
    return na < nb ? -1 : na > nb ? 1 : a.path < b.path ? -1 : a.path > b.path ? 1 : 0
  })
}

// A repo under a searched folder starts with its code indexed. `proposed` lists repos already
// offered, so one the user switched off stays off; `blocked` are worktrees, whose code the main
// repository already covers.
function addCode(state, repos, proposed, blocked) {
  var code = state.code.slice()
  repos.forEach(function(repo) {
    if (proposed.indexOf(repo.path) >= 0 || code.indexOf(repo.path) >= 0) return
    if (blocked.some(function(folder) { return isInside(repo.path, folder) })) return
    if (searched(repo.path, state)) code.push(repo.path)
  })
  return make(state.chosen, state.skipped, code)
}
