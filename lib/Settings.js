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
    warmMinutes: integer(value.warmMinutes, 5, 0, 60)}
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
