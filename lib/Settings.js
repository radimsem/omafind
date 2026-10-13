.pragma library

function integer(value, fallback, low, high) {
  return typeof value === "number" && isFinite(value) && Math.floor(value) === value
    ? Math.max(low, Math.min(high, value)) : fallback
}

function roots(value) {
  if (!Array.isArray(value)) return []
  return value.filter(function(root) {
    return root && typeof root === "object" && typeof root.path === "string"
      && root.path.charAt(0) === "/" && typeof root.volume === "string"
      && Array.isArray(root.excludes) && root.excludes.every(function(path) {
        return typeof path === "string"
      })
  }).map(function(root) {
    return {path: root.path, volume: root.volume, excludes: root.excludes.slice()}
  })
}

var MODS = ["SUPER", "SHIFT", "CTRL", "ALT"]

// Mirrors valid_shortcut in helper/omafindd/settings.py.
function shortcut(value) {
  if (typeof value !== "string"
      || !/^(?:SUPER|SHIFT|CTRL|ALT)(?:\s*\+\s*(?:SUPER|SHIFT|CTRL|ALT))*\s*\+\s*[A-Z0-9_]+$/.test(value)) {
    return "SUPER + E"
  }
  var parts = value.split("+").map(function(part) { return part.trim() })
  var unique = parts.filter(function(part, index) { return parts.indexOf(part) === index })
  return unique.length === parts.length && MODS.indexOf(parts[parts.length - 1]) === -1 ? value : "SUPER + E"
}

function normalize(entry) {
  var value = entry && typeof entry === "object" && !Array.isArray(entry) ? entry : {}
  return {setupDone: value.setupDone === true,
    gpu: value.gpu === "never" ? "never" : "auto",
    audio: typeof value.audio === "boolean" ? value.audio : true,
    roots: roots(value.roots), maxResults: integer(value.maxResults, 40, 10, 200),
    codeRoots: Array.isArray(value.codeRoots) ? value.codeRoots.filter(function(path) {
      return typeof path === "string" && path.charAt(0) === "/"
    }) : [],
    imageBudget: [70, 140, 280].indexOf(value.imageBudget) >= 0 ? value.imageBudget : 140,
    warmMinutes: integer(value.warmMinutes, 5, 0, 60), shortcut: shortcut(value.shortcut)}
}

function setOwn(object, key, value) {
  Object.defineProperty(object, key, {value: value, writable: true, enumerable: true, configurable: true})
}

function merge(entry, changes) {
  var merged = {}
  var key
  for (key in entry) {
    if (Object.prototype.hasOwnProperty.call(entry, key)) setOwn(merged, key, entry[key])
  }
  for (key in changes) {
    if (Object.prototype.hasOwnProperty.call(changes, key)) setOwn(merged, key, changes[key])
  }
  var settings = normalize(merged)
  for (key in settings) setOwn(merged, key, settings[key])
  return merged
}

function findEntry(config, id) {
  if (!config || typeof config !== "object" || Array.isArray(config)) return null
  var layout = config.bar && config.bar.layout
  var sections = layout ? [layout.left, layout.center, layout.right] : []
  sections.push(config.plugins)
  for (var i = 0; i < sections.length; i++) {
    var entries = sections[i]
    if (!Array.isArray(entries)) continue
    for (var j = 0; j < entries.length; j++) {
      var entry = entries[j]
      if (entry && typeof entry === "object" && !Array.isArray(entry) && entry.id === id) return entry
    }
  }
  return null
}
