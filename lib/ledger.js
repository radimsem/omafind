.pragma library

// Mirrors helper/omafindd/leftout.py: secrets are separate from directory own counts.
var PRECEDENCE = ["secrets", "user", "generated", "no-kind"]
var KINDS = ["text", "pdf", "image", "video", "audio"]

function count(n) {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",")
}

function token(k, v, tone) {
  return {k: k, v: String(v), tone: tone || "plain"}
}

function inside(path, folder) {
  return folder === "" || path === folder || path.indexOf(folder + "/") === 0
}

function owner(dirPath, excludes) {
  var result = null
  excludes.forEach(function(entry) {
    if (!inside(dirPath, entry.path)) return
    var rank = PRECEDENCE.indexOf(entry.rule)
    if (!result || rank < PRECEDENCE.indexOf(result.rule)
        || rank === PRECEDENCE.indexOf(result.rule) && entry.path.length < result.path.length) result = entry
  })
  return result
}

function zero() {
  return {text: 0, pdf: 0, image: 0, video: 0, audio: 0}
}

function sum(counts) {
  return KINDS.reduce(function(total, kind) { return total + counts[kind] }, 0)
}

function add(target, counts) {
  KINDS.forEach(function(kind) { target[kind] += counts[kind] || 0 })
}

function compute(tree, excludes) {
  var found = zero()
  var kept = zero()
  var leftOut = zero()
  var entries = excludes.map(function(entry) {
    var dir = tree.dirs.find(function(dir) { return dir.path === entry.path })
    return {path: entry.path, rule: entry.rule, counts: zero(), files: 0,
      evidence: entry.rule === "user" ? null : dir && dir.evidence ? dir.evidence : entry.evidence || {},
      added: entry.added == null ? null : entry.added}
  })
  tree.dirs.forEach(function(dir) {
    add(found, dir.own)
    var exclude = owner(dir.path, excludes)
    if (exclude) add(entries[excludes.indexOf(exclude)].counts, dir.own)
    else add(kept, dir.own)
  })
  entries.forEach(function(entry) {
    entry.files = sum(entry.counts)
    if (entry.rule === "user") entry.evidence = {files: entry.files, added: entry.added}
    add(leftOut, entry.counts)
  })
  var secrets = tree.secrets && (tree.secrets.files > 0 || (tree.secrets.evidence.exts || []).length) ? tree.secrets : null
  if (secrets) {
    var secretCounts = zero()
    add(secretCounts, secrets.counts)
    add(found, secretCounts)
    add(leftOut, secretCounts)
    entries.push({path: "**", rule: "secrets", counts: secretCounts, files: secrets.files,
      evidence: secrets.evidence, added: null})
  }
  found.total = sum(found)
  kept.total = sum(kept)
  leftOut.total = sum(leftOut)
  return {found: found, kept: kept, leftOut: leftOut, entries: entries, secrets: secrets, dirs: excludes.length}
}

function header(ledger) {
  return count(ledger.entries.length) + " entries · " + count(ledger.leftOut.total) + " files"
}

function entryFacts(entry) {
  var evidence = entry.evidence || {}
  var tokens = []
  if (entry.rule === "user") {
    var added = entry.added == null ? evidence.added : entry.added
    if (added != null) tokens.push(token("added", formatAdded(added)))
    tokens.push(token("files", count(entry.files)))
  } else if (entry.rule === "generated") {
    if (evidence.pattern) tokens.push(token("pattern", evidence.pattern))
    if (evidence.match) tokens.push(token("match", evidence.match.map(count).join("/")))
    if (evidence.dataset_limit != null) tokens.push(token("dataset limit", count(evidence.dataset_limit)))
  } else {
    if (entry.rule === "no-kind") tokens.push(token("files", count(evidence.files)))
    ;(evidence.exts || []).forEach(function(ext) { tokens.push(token(ext[0], count(ext[1]))) })
    if (entry.rule === "no-kind") tokens.push(token("searchable", "0", "strong"))
    else if (evidence.in && evidence.in.length) tokens.push(token("in", evidence.in.join(", ")))
  }
  return tokens
}

function footer(ledger, rates, device, root, home) {
  var bytes = 0
  var seconds = 0
  KINDS.forEach(function(kind) {
    bytes += ledger.kept[kind] * rates.bytes[kind]
    seconds += ledger.kept[kind] * rates[device][kind]
  })
  var base = (home || "").replace(/\/$/, "")
  var path = base && inside(root, base) ? "~" + root.slice(base.length) : root
  var size = bytes < 1e6 ? "< 1 MB" : Math.round(bytes / 1e6) + " MB"
  var time = seconds < 60 ? "< 1 min" : "~" + Math.round(seconds / 60) + " min"
  return {found: count(ledger.found.total), leftOut: count(ledger.leftOut.total), kept: count(ledger.kept.total),
    leftSub: count(ledger.dirs) + " dirs · " + count(ledger.secrets ? ledger.secrets.files : 0) + " secrets",
    keptLabel: "Kept in " + path, keptSub: "index " + size + " · time " + time}
}

function summary(ledger) {
  return {found: ledger.found.total, kept: ledger.kept.total, entries: ledger.entries}
}

function addExclude(excludes, path, rule, addedAt) {
  var result = excludes.slice()
  if (!result.some(function(entry) { return entry.path === path })) result.push({path: path, rule: rule, added: addedAt})
  return result
}

function removeExclude(excludes, path) {
  return excludes.filter(function(entry) { return entry.path !== path })
}

function formatAdded(epochMs) {
  var date = new Date(epochMs)
  function pad(n) { return n < 10 ? "0" + n : String(n) }
  return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate())
    + " " + pad(date.getHours()) + ":" + pad(date.getMinutes())
}
