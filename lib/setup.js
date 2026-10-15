.pragma library

var KINDS = ["text", "pdf", "image", "video", "audio"]
var KIND_LABELS = {text: "Text", pdf: "PDF", image: "Images", video: "Video", audio: "Audio"}
var DATASET_KINDS = {image: "images", video: "videos", audio: "audio"}
// The step 1 hint's build estimate, from the board's "Built in 3 min 12 s".
var BUILD_MINUTES = 3

function count(n) {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",")
}

function token(k, v, tone) {
  return {k: k, v: String(v), tone: tone || "plain"}
}

function displayPath(abs, home) {
  var base = (home || "").replace(/\/$/, "")
  return base && (abs === base || abs.indexOf(base + "/") === 0) ? "~" + abs.slice(base.length) : abs
}

function mb(bytes) {
  return bytes < 1e6 ? "< 1 MB" : Math.round(bytes / 1e6) + " MB"
}

function minutes(seconds) {
  return seconds < 60 ? "< 1 min" : Math.round(seconds / 60) + " min"
}

function approxMinutes(seconds) {
  return seconds < 60 ? "< 1 min" : "~" + minutes(seconds)
}

function treeTime(seconds) {
  if (seconds < 0.5) return "< 1 s"
  if (seconds < 90) return Math.round(seconds) + " s"
  if (seconds < 5400) return Math.round(seconds / 60) + " min"
  return (seconds / 3600).toFixed(1) + " h"
}

function buildTime(seconds) {
  var value = Math.round(seconds)
  var tail = value % 60
  return value < 60 ? value + " s" : Math.floor(value / 60) + " min " + (tail < 10 ? "0" : "") + tail + " s"
}

function engineReady(rp) {
  return !!rp && rp.state === "done"
}

function step(facts) {
  if (facts.back || !engineReady(facts.runtimeProgress)) return 1
  return facts.progress ? 3 : 2
}

function chips(current) {
  return ["Search engine", "Folders", "Index"].map(function(label, index) {
    return {label: label, state: index + 1 < current ? "done" : index + 1 === current ? "cur" : "todo",
      mark: index + 1 < current ? "✓" : String(index + 1)}
  })
}

function stepLabel(current) {
  return "Step " + current + " of 3"
}


function engineButton(rp, helperReady) {
  var state = rp ? rp.state : "idle"
  return {text: state === "running" ? "Pause" : state === "paused" ? "Resume" : state === "failed" ? "Retry" : "Install",
    visible: state !== "done", enabled: !!helperReady, action: state === "running" ? "pause" : "install"}
}

function helperTask(connection) {
  var ready = !!connection && connection.unit === "enabled" && connection.socket === "ready"
  return {mark: ready ? "ok" : "wait", value: ready ? "Installed" : null, install: !ready,
    tokens: [token("unit", ready ? "omafind.service active" : "omafind.service " + (connection ? connection.unit : "unknown")),
      token("venv", "~/.local/share/omafind")]}
}

// A run that failed before the server was built; the model was never asked for.
function buildFailed(rp) {
  return !!rp && rp.state === "failed" && !(rp.build && rp.build.state === "ok")
}

function serverTask(rp) {
  var build = rp && rp.build ? rp.build : {}
  var state = rp ? rp.state : "idle"
  var mark = build.state === "ok" ? "ok" : state === "running" ? "run"
    : build.state === "failed" || buildFailed(rp) ? "failed" : "wait"
  var value = mark === "ok" ? (build.seconds == null ? "Installed" : "Built in " + buildTime(build.seconds))
    : mark === "failed" ? "Failed" : state === "paused" ? "Paused"
    : mark === "run" ? "Building" + (build.seconds == null ? "" : " · " + buildTime(build.seconds)) : "Not installed"
  var tokens = [token("llama.cpp", build.tag || "b11461"), token("backend", build.backend || "Vulkan")]
  if (build.gpu) tokens.push(token("gpu", build.gpu))
  return {mark: mark, value: value, valueTone: mark === "ok" ? "ok" : mark === "failed" ? "fail" : "plain", tokens: tokens}
}

function modelTask(rp) {
  var state = rp ? rp.state : "idle"
  var running = state === "running" && rp.step === "download"
  var failed = state === "failed" && !buildFailed(rp)
  var got = null
  if (running) {
    got = [token("got", rp.done + "/" + rp.total + " MB")]
    got.push(rp.left_seconds == null ? token("verify", "sha256") : token("left", approxMinutes(rp.left_seconds)))
  }
  return {mark: state === "done" ? "ok" : failed ? "failed" : running ? "run" : "wait",
    value: state === "done" ? "Installed" : state === "paused" ? "Paused" : failed ? "Failed" : running ? null
      : state === "running" ? "Waiting" : "Not downloaded",
    valueTone: state === "done" ? "ok" : failed ? "fail" : "plain",
    tokens: [token("repo", "ggml-org/embeddinggemma-2-GGUF"), token("quant", "Q8_0"), token("license", "Apache 2.0"), token("verify", "sha256")], got: got}
}

function fraction(done, total) {
  return total > 0 ? Math.max(0, Math.min(1, done / total)) : 0
}

function fileLines(rp) {
  var waiting = rp && (rp.state === "running" || rp.state === "paused") ? "queued" : "not downloaded"
  return ["model", "mmproj"].filter(function(key) { return rp && rp.files && rp.files[key] }).map(function(key) {
    var file = rp.files[key]
    var done = file.state === "ok"
    var active = file.state === "run" || file.state === "verify"
    return {icon: done ? "✓" : active ? "↓" : "·", tone: done ? "ok" : active ? "accent" : "dim", name: file.name,
      mb: file.state === "run" ? file.done + " of " + file.total + " MB"
        : file.total + " MB · " + (done ? "verified" : file.state === "verify" ? "checking sha256" : waiting),
      fraction: done ? 1 : fraction(file.done, file.total), done: done}
  })
}

function totalFraction(rp) {
  return rp ? fraction(rp.done, rp.total) : 0
}

// Failures show in the error card instead of the hint.
function engineHint(rp) {
  var state = rp ? rp.state : "idle"
  if (state === "failed") return ""
  if (state === "done") return "Everything is installed. Folders are next."
  if (state === "running" || state === "paused") return "You can close this. Installing keeps going."
  var model = "the model" + (rp && rp.total ? " (" + rp.total + " " + (rp.unit || "MB") + ")" : "")
  if (rp && rp.build && rp.build.state === "ok") return "Install downloads " + model + "."
  return "Install builds the server (about " + BUILD_MINUTES + " min) and downloads " + model + "."
}


function estimate(counts, rates, device) {
  var result = {bytes: 0, seconds: 0}
  if (!counts || !rates || !rates.bytes || !rates[device]) return result
  KINDS.forEach(function(kind) {
    result.bytes += (counts[kind] || 0) * rates.bytes[kind]
    result.seconds += (counts[kind] || 0) * rates[device][kind]
  })
  return result
}


function totalFacts(total, device) {
  return [token("selected", count(total.files) + " files", "strong"), token("index", mb(total.bytes), "strong"),
    token("time", approxMinutes(total.seconds), "strong"), token("device", device ? device.toUpperCase() : "–")]
}

function kindRows(progress) {
  var kinds = progress && progress.kinds ? progress.kinds : {}
  return KINDS.map(function(kind) {
    var row = kinds[kind] || {done: 0, total: 0}
    var done = row.total > 0 && row.done >= row.total
    var text = count(row.done) + " of " + count(row.total)
    if (kind === "audio" && row.total === 0 && kinds.video && kinds.video.total > 0) {
      text = "soundtracks of " + count(kinds.video.total) + " videos"
    } else if (done) text += " done"
    else if (kind === "pdf" && row.pages != null) text += " · " + count(row.pages) + " pages"
    else if (kind === "image" && row.ocr != null) text += " · " + count(row.ocr) + " OCR'd"
    else text += " · " + (row.done > 0 && progress.running ? "running" : "queued")
    return {label: KIND_LABELS[kind], fraction: fraction(row.done, row.total), done: done, text: text}
  })
}

function indexHead(progress, rates) {
  var p = progress || {done: 0, queued: 0, running: false, kinds: {}}
  var total = p.done + p.queued
  var facts = [token("of", count(total) + " files")]
  var side = []
  if (p.running && p.device && rates) {
    var remaining = {}
    KINDS.forEach(function(kind) {
      var row = p.kinds[kind] || {total: 0, done: 0}
      remaining[kind] = Math.max(0, row.total - row.done)
    })
    facts.push(token("left", approxMinutes(estimate(remaining, rates, p.device).seconds)))
  }
  if (p.device) side.push(token("device", p.device.toUpperCase()))
  if (p.vram_gb != null) side.push(token("vram", p.vram_gb + " GB"))
  if (!p.running && p.exit != null && p.exit !== 0) side.push(token("exit", p.exit, "warn"))
  return {count: count(p.done), facts: facts, side: side, spinning: !!p.running, fraction: fraction(p.done, total)}
}

function indexTitle(progress, failure) {
  if (failure || (progress && !progress.running && (progress.queued > 0 || progress.exit))) return "Indexing stopped"
  if (progress && !progress.running && progress.done > 0 && !progress.queued) return "Indexing finished"
  return "Indexing your files"
}

function problemFacts(progress) {
  var tokens = []
  ;["skipped", "failed"].forEach(function(group) {
    var counts = progress && progress[group] || {}
    var keys = Object.keys(counts).filter(function(key) { return counts[key] > 0 })
    if (!keys.length) return
    tokens.push(token(group, ""))
    keys.forEach(function(key) { tokens.push(token(key, count(counts[key]), "strong")) })
  })
  return tokens
}

function scanFacts(folders, walks) {
  var list = Object.keys(walks || {}).map(function(root) { return walks[root] })
  if (!list.length || list.some(function(walk) { return !walk.done })) {
    return [token("folders", count(folders)), token("scanning", "")]
  }
  if (list.some(function(walk) { return !!walk.error })) return [token("folders", count(folders))]
  var seconds = Math.max.apply(null, list.map(function(walk) { return walk.seconds || 0 }))
  return [token("scanned in", seconds.toFixed(1) + " s")]
}

function walkError(walks) {
  for (var root in walks || {}) if (walks[root].error) return walks[root].error
  return ""
}

// A per-file problem row: its code with the extractor's detail, then the path.
function problemTokens(problem, home) {
  return [token(problem.code || problem.reason || "failed", problem.detail || ""),
    token("path", displayPath(problem.path, home))]
}

function datasetFacts(evidence) {
  return [token(DATASET_KINDS[evidence.kind] || evidence.kind, count(evidence.files)),
    token("named", evidence.named + "%")]
}

function panelSize(current) {
  if (current === 1) return {width: 760, height: 474}
  if (current === 3) return {width: 920, height: 574}
  return {width: 1120, height: 992}
}
