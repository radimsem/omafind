.pragma library

// Folder marks mirror helper/omafindd/selection.py with root-relative paths.
var KINDS = ["text", "pdf", "image", "video", "audio"]
var PRECEDENCE = ["secrets", "user", "generated", "no-kind"]

function count(n) {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",")
}

function token(k, v, tone) {
  return {k: k, v: String(v), tone: tone || "plain"}
}

function isInside(path, folder) {
  return folder === "" || path === folder || path.indexOf(folder.replace(/\/$/, "") + "/") === 0
}

function parent(path) {
  var index = path.lastIndexOf("/")
  return index < 0 ? "" : path.slice(0, index)
}

// DigUp FolderSelection: the root and every chosen folder are searched, minus the skips inside
// them. A chosen folder inside a skipped one is searched whole while the skip keeps the rest out.
function searched(path, excludes, chosen) {
  return [""].concat(chosen || []).some(function(folder) {
    return isInside(path, folder) && !excludes.some(function(entry) {
      return isInside(entry.path, folder) && (entry.path !== folder || folder === "") && isInside(path, entry.path)
    })
  })
}

function mark(path, excludes, chosen) {
  if (searched(path, excludes, chosen)) {
    return excludes.some(function(entry) {
      return entry.path !== path && isInside(entry.path, path) && !searched(entry.path, excludes, chosen)
    }) ? "mixed" : "on"
  }
  return (chosen || []).some(function(folder) { return folder !== path && isInside(folder, path) }) ? "mixed" : "off"
}

function children(tree, path) {
  return tree.dirs.filter(function(dir) { return dir.path !== "" && parent(dir.path) === path })
}

function keptDirs(tree, path, excludes, chosen) {
  var dirs = children(tree, path)
  return {kept: dirs.filter(function(dir) { return mark(dir.path, excludes, chosen) !== "off" }).length, total: dirs.length}
}

// `chosen` holds root-relative folders searched although an ancestor is left out.
function initial(tree, excludes, chosen) {
  return {tree: tree, excludes: excludes.map(function(entry) { return Object.assign({}, entry) }),
    chosen: (chosen || []).slice(), expanded: {}, filter: "", history: [], last: null}
}

function changed(state, excludes, chosen, last) {
  return Object.assign({}, state, {excludes: excludes, chosen: chosen,
    history: state.history.concat([{excludes: state.excludes, chosen: state.chosen || []}]), last: last})
}

function toggle(state, path, now) {
  var chosen = state.chosen || []
  var outside = function(folder) { return !isInside(folder, path) }
  if (mark(path, state.excludes, chosen) === "on") {
    var kept = chosen.filter(outside)
    var excludes = state.excludes
    if (searched(path, excludes, kept) && !excludes.some(function(entry) { return entry.path === path })) {
      excludes = excludes.concat([{path: path, rule: "user", added: now}])
    }
    return changed(state, excludes, kept, {path: path, action: "leave", at: now})
  }
  var remaining = state.excludes.filter(function(entry) { return !isInside(entry.path, path) })
  var restored = chosen.filter(outside)
  if (!searched(path, remaining, restored)) restored = restored.concat([path])
  return changed(state, remaining, restored, {path: path, action: "restore", at: now})
}

function selectByRule(state, rule, now) {
  var excludes = state.excludes.slice()
  state.tree.dirs.forEach(function(dir) {
    var matches = rule === "big" ? dir.path !== "" && files(dir.sub) > 1000 : dir.rule === rule
    if (matches && !excludes.some(function(entry) { return entry.path === dir.path })) {
      excludes.push({path: dir.path, rule: rule === "big" ? "user" : rule, added: now})
    }
  })
  // A chosen folder is searched despite an exclude at its own path, so the rule must unchoose it.
  var chosen = (state.chosen || []).filter(function(folder) {
    return !excludes.some(function(entry) { return entry.path === folder })
  })
  return changed(state, excludes, chosen, null)
}

function ruleCounts(tree, excludes) {
  var counts = {"no-kind": 0, generated: 0, big: 0}
  tree.dirs.forEach(function(dir) {
    if (dir.rule === "no-kind" || dir.rule === "generated") counts[dir.rule] += 1
    if (dir.path !== "" && files(dir.sub) > 1000) counts.big += 1
  })
  return counts
}

function undo(state) {
  if (!state.history.length) return Object.assign({}, state, {last: null})
  var previous = state.history[state.history.length - 1]
  return Object.assign({}, state, {excludes: previous.excludes, chosen: previous.chosen, history: state.history.slice(0, -1), last: null})
}

function expand(state, path, open) {
  var expanded = Object.assign({}, state.expanded)
  Object.defineProperty(expanded, path, {value: !!open, enumerable: true, configurable: true, writable: true})
  return Object.assign({}, state, {expanded: expanded})
}

function setFilter(state, text) {
  return Object.assign({}, state, {filter: text})
}

function files(counts) {
  return KINDS.reduce(function(n, kind) { return n + (counts[kind] || 0) }, 0)
}

function excludeOwner(path, excludes) {
  var result = null
  excludes.forEach(function(entry) {
    if (!isInside(path, entry.path)) return
    var rank = PRECEDENCE.indexOf(entry.rule)
    if (!result || rank < PRECEDENCE.indexOf(result.rule)
        || rank === PRECEDENCE.indexOf(result.rule) && entry.path.length < result.path.length) result = entry
  })
  return result
}

function evidenceFacts(dir, exclude) {
  var evidence = dir.evidence || {}
  var tokens = []
  if (exclude.rule === "user") {
    if (exclude.added != null) {
      var date = new Date(exclude.added)
      function pad(n) { return n < 10 ? "0" + n : String(n) }
      tokens.push(token("added", date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate())
        + " " + pad(date.getHours()) + ":" + pad(date.getMinutes())))
    }
    tokens.push(token("files", count(files(dir.sub))))
  } else if (exclude.rule === "generated") {
    if (evidence.pattern) tokens.push(token("pattern", evidence.pattern))
    if (evidence.match) tokens.push(token("match", evidence.match.map(count).join("/")))
    if (evidence.dataset_limit != null) tokens.push(token("dataset limit", count(evidence.dataset_limit)))
  } else if (exclude.rule === "no-kind") {
    tokens.push(token("files", count(evidence.files == null ? dir.all_sub : evidence.files)))
    ;(evidence.exts || []).forEach(function(ext) { tokens.push(token(ext[0], count(ext[1]))) })
    tokens.push(token("searchable", "0", "strong"))
  }
  return tokens
}

// Own counts of every kept dir in the subtree, the same partition the ledger uses, so a parent
// shows only what stays indexed.
function keptCounts(tree, dir, excludes, chosen) {
  var kept = {}
  KINDS.forEach(function(kind) { kept[kind] = 0 })
  tree.dirs.forEach(function(other) {
    if (!isInside(other.path, dir.path) || !searched(other.path, excludes, chosen)) return
    KINDS.forEach(function(kind) { kept[kind] += other.own[kind] || 0 })
  })
  return kept
}

function rows(tree, state) {
  var filter = state.filter.toLowerCase()
  var matches = filter ? tree.dirs.filter(function(dir) { return dir.path.toLowerCase().indexOf(filter) >= 0 }) : []
  var visible = tree.dirs.filter(function(dir) {
    if (dir.path === "") return false
    if (filter) return matches.some(function(match) { return isInside(match.path, dir.path) })
    var ancestor = parent(dir.path)
    while (ancestor !== "") {
      if (!Object.prototype.hasOwnProperty.call(state.expanded, ancestor) || !state.expanded[ancestor]) return false
      ancestor = parent(ancestor)
    }
    return true
  })
  return visible.map(function(dir) {
    var chosen = state.chosen || []
    var status = mark(dir.path, state.excludes, chosen)
    var exclude = searched(dir.path, state.excludes, chosen) ? null : excludeOwner(dir.path, state.excludes)
    var hot = !!state.last && state.last.action === "restore" && state.last.path === dir.path
    var facts = []
    if (hot) facts.push(token("restored", "just now"))
    else if (status === "mixed") {
      var kept = keptDirs(tree, dir.path, state.excludes, chosen)
      facts.push(token("kept", count(kept.kept) + "/" + count(kept.total) + " dirs"))
    } else if (exclude) facts = evidenceFacts(dir, exclude)
    else {
      if (dir.dirs > 1) facts.push(token("dirs", count(dir.dirs)))
      facts = facts.concat((dir.exts || []).map(function(ext) { return token(ext[0], count(ext[1])) }))
    }
    var counts = status === "off" ? dir.sub : keptCounts(tree, dir, state.excludes, chosen)
    var n = files(counts)
    return {path: dir.path, name: dir.path.slice(dir.path.lastIndexOf("/") + 1), depth: dir.path.split("/").length - 1,
      mark: status, out: status === "off", rule: exclude ? exclude.rule : dir.rule,
      counts: counts, files: n, all: dir.all_sub, exts: dir.exts, facts: facts, hot: hot,
      expandable: children(tree, dir.path).length > 0 || dir.dirs > 1,
      expanded: filter ? matches.some(function(match) { return match.path !== dir.path && isInside(match.path, dir.path) })
        : Object.prototype.hasOwnProperty.call(state.expanded, dir.path) && !!state.expanded[dir.path],
      barWidth: barWidth(n), segments: KINDS.filter(function(kind) { return counts[kind] > 0 }).map(function(kind) { return {kind: kind, n: counts[kind]} })}
  })
}

function barWidth(n) {
  return n ? Math.round(18.7 + 10.83 * Math.log(n)) : 18
}

// Ledger for a draft with chosen folders. `compute` is ledger.js compute(), which knows only
// excludes: dirs a chosen folder brings back are left out of its input and added to kept.
function ledger(tree, excludes, chosen, compute) {
  var back = tree.dirs.filter(function(dir) {
    return excludes.some(function(entry) { return isInside(dir.path, entry.path) }) && searched(dir.path, excludes, chosen)
  })
  var result = compute(Object.assign({}, tree, {dirs: tree.dirs.filter(function(dir) { return back.indexOf(dir) < 0 })}), excludes)
  back.forEach(function(dir) {
    KINDS.forEach(function(kind) {
      result.found[kind] += dir.own[kind] || 0
      result.kept[kind] += dir.own[kind] || 0
    })
  })
  result.found.total = files(result.found)
  result.kept.total = files(result.kept)
  return result
}

function toRoots(chosen, skipped, volumeOf) {
  var folders = chosen.filter(function(path, index) {
    if (chosen.indexOf(path) !== index) return false
    var outer = chosen.filter(function(folder) { return folder !== path && isInside(path, folder) })
    return !outer.some(function(folder) {
      return !skipped.some(function(skip) { return isInside(path, skip) && isInside(skip, folder) && skip !== folder })
    })
  })
  return folders.map(function(path) {
    return {path: path, volume: volumeOf(path), excludes: skipped.filter(function(skip, index) {
      return skip !== path && isInside(skip, path) && skipped.indexOf(skip) === index
    }).map(function(skip) { return skip.slice(path === "/" ? 1 : path.replace(/\/$/, "").length + 1) })}
  })
}
