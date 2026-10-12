.pragma library

function normalize(entry) {
  var value = entry && typeof entry === "object" && !Array.isArray(entry) ? entry : {}
  return {setupDone: value.setupDone === true,
    gpu: value.gpu === "never" ? "never" : "auto",
    audio: typeof value.audio === "boolean" ? value.audio : true}
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
