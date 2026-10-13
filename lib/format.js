.pragma library

function duration(seconds) {
  var value = Math.floor(seconds)
  var hours = Math.floor(value / 3600)
  var minutes = Math.floor(value / 60) % 60
  var tail = (value % 60 < 10 ? "0" : "") + value % 60
  return hours ? hours + ":" + (minutes < 10 ? "0" : "") + minutes + ":" + tail
    : Math.floor(value / 60) + ":" + tail
}

function windowCaption(start, end, total) {
  return duration(start) + " – " + duration(end) + " of " + duration(total)
}

function count(n) {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",")
}

function size(bytes) {
  var units = ["B", "KB", "MB", "GB", "TB"]
  var unit = 0
  var value = bytes
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000
    unit += 1
  }
  return value.toFixed(unit && value < 10 ? 1 : 0) + " " + units[unit]
}

function date(mtimeSeconds) {
  var value = new Date(mtimeSeconds * 1000)
  var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
  return months[value.getMonth()] + " " + value.getDate() + ", " + value.getFullYear()
}

function kindLabel(kind) {
  return {image: "Image", video: "Video", audio: "Audio", pdf: "PDF", text: "Text", code: "Code"}[kind]
}

function meta(item) {
  var parts = []
  var info = item.info || {}
  var label = kindLabel(item.kind)
  if (label) parts.push(label)
  if (item.mtime != null) parts.push(date(item.mtime))
  if ((item.kind === "video" || item.kind === "audio") && info.duration != null) {
    parts.push(duration(info.duration))
  }
  if (item.kind === "pdf" && info.pages != null) parts.push(count(info.pages) + " pages")
  if (item.size != null) parts.push(size(item.size))
  return parts.join(" · ")
}

function at(item) {
  if (item.kind === "image") return null
  var line = item.kind === "code" && item.open_line != null ? item.open_line : item.loc
  if (line == null) return null
  if (item.kind === "video" || item.kind === "audio") return duration(line)
  if (item.kind === "pdf") return "p. " + line
  if (item.kind === "text" || item.kind === "code") {
    var range = (item.kind !== "code" || item.open_line == null) && item.loc_end > line
    return "L" + line + (range ? "–" + item.loc_end : "")
  }
  return null
}

function why(item, preview) {
  var tokens = []
  var values = [item.leg, item.part, at(item), (item.hits || []).join(", "),
    item.z == null ? null : item.z.toFixed(1)]
  var keys = ["leg", "part", "at", "hits", "z"]
  for (var i = 0; i < keys.length; i++) {
    if (values[i] != null && values[i] !== "") {
      tokens.push({k: keys[i], v: values[i], tone: i === 2 || i === 3 ? "accent" : "plain"})
    }
  }
  if (["video", "pdf", "text", "code"].indexOf(item.kind) >= 0 && preview && preview.opener) {
    tokens.push({k: "opener", v: preview.opener, tone: "plain"})
  }
  return tokens
}

function snippetRuns(snippet) {
  var runs = []
  for (var i = 0; snippet && i < snippet.length; i++) {
    var run = snippet[i]
    var last = runs[runs.length - 1]
    if (last && last.m === run.m) last.t += run.t
    else runs.push({t: run.t, m: run.m})
  }
  return runs
}
