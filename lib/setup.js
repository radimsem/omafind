.pragma library

var KINDS = ["text", "pdf", "image", "video", "audio"]
var KIND_LABELS = {text: "Text", pdf: "PDF", image: "Images", video: "Video", audio: "Audio"}
var CHORDS = ["SUPER + E", "SUPER + D", "SUPER + U"]

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

function panelSize(current, sub) {
  if (current === 1) return {width: 760, height: 474}
  if (current === 3) return {width: 920, height: 574}
  return {width: 1120, height: sub === "tree" ? 948 : 992}
}

function engineButton(rp, helperReady) {
  var state = rp ? rp.state : "idle"
  return {text: state === "running" ? "Pause" : state === "paused" || state === "failed" ? "Resume" : "Download",
    visible: state !== "done", enabled: !!helperReady, action: state === "running" ? "pause" : "install"}
}

function helperTask(connection) {
  var ready = !!connection && connection.unit === "enabled" && connection.socket === "ready"
  return {mark: ready ? "ok" : "wait", value: ready ? "Installed" : null, install: !ready,
    tokens: [token("unit", ready ? "omafind.service active" : "omafind.service " + (connection ? connection.unit : "unknown")),
      token("venv", "~/.local/share/omafind")]}
}

function serverTask(rp) {
  var build = rp && rp.build ? rp.build : {}
  var mark = build.state === "ok" ? "ok" : build.state === "run" ? "run" : build.state === "failed" ? "failed" : "wait"
  if (rp && rp.state === "paused" && mark === "run") mark = "wait"
  var value = mark === "ok" ? (build.seconds == null ? "Installed" : "Built in " + buildTime(build.seconds))
    : mark === "failed" ? "Failed" : rp && rp.state === "paused" ? "Paused"
    : mark === "run" ? "Building" + (build.seconds == null ? "" : " · " + buildTime(build.seconds)) : "Starting"
  var tokens = [token("llama.cpp", build.tag || "b11461"), token("backend", build.backend || "Vulkan")]
  if (build.gpu) tokens.push(token("gpu", build.gpu))
  return {mark: mark, value: value, valueTone: mark === "ok" ? "ok" : mark === "failed" ? "fail" : "plain", tokens: tokens}
}

function modelTask(rp) {
  var state = rp ? rp.state : "idle"
  var running = state === "running" && rp.step === "download"
  var got = null
  if (running) {
    got = [token("got", rp.done + "/" + rp.total + " MB")]
    got.push(rp.left_seconds == null ? token("verify", "sha256") : token("left", approxMinutes(rp.left_seconds)))
  }
  return {mark: state === "done" ? "ok" : state === "failed" ? "failed" : running ? "run" : "wait",
    value: state === "done" ? "Verified" : state === "paused" ? "Paused" : state === "failed" ? "Failed" : running ? null : "Queued",
    valueTone: state === "done" ? "ok" : state === "failed" ? "fail" : "plain",
    tokens: [token("repo", "ggml-org/embeddinggemma-2-GGUF"), token("quant", "Q8_0"), token("license", "Apache 2.0"), token("verify", "sha256")], got: got}
}

function fraction(done, total) {
  return total > 0 ? Math.max(0, Math.min(1, done / total)) : 0
}

function fileLines(rp) {
  return ["model", "mmproj"].filter(function(key) { return rp && rp.files && rp.files[key] }).map(function(key) {
    var file = rp.files[key]
    var done = file.state === "ok"
    var active = file.state === "run" || file.state === "verify"
    return {icon: done ? "✓" : active ? "↓" : "·", tone: done ? "ok" : active ? "accent" : "dim", name: file.name,
      mb: file.state === "run" ? file.done + " of " + file.total + " MB"
        : file.total + " MB · " + (done ? "verified" : file.state === "verify" ? "checking sha256" : "queued"),
      fraction: done ? 1 : fraction(file.done, file.total), done: done}
  })
}

function totalFraction(rp) {
  return rp ? fraction(rp.done, rp.total) : 0
}

function engineHint(rp) {
  return rp && rp.reason ? rp.reason : engineReady(rp) ? "Everything is installed. Folders are next."
    : "You can close this. The download keeps going."
}

function scanFacts(body) {
  var scan = body.scan
  return [token("scan", scan.seconds + " s"), token("roots", scan.roots.join(", ")), token("volumes", count(scan.volumes)),
    token("dirs", count(scan.dirs)), token("read", "names only")]
}

function scanningFacts() {
  return [token("roots", "$HOME"), token("read", "names only")]
}

function rowFacts(candidate, ledgerSummary) {
  var result = [token("dirs", count(candidate.dirs))]
  var entries = ledgerSummary ? ledgerSummary.entries : candidate.left_out
  var found = ledgerSummary ? ledgerSummary.found : candidate.found
  var kept = ledgerSummary ? ledgerSummary.kept : candidate.kept
  if (entries && entries.length) {
    if (kept !== found) result.push(token("kept", count(kept) + "/" + count(found)))
    result.push(token("left out", count(entries.length)))
    return result
  }
  if (candidate.section === "elsewhere") {
    if (candidate.git) result.push(token("git", "repo"))
    result.push(token("rule", candidate.git ? "gitignore, code" : "dense"))
  }
  return result.concat((candidate.exts || []).slice(0, 2).map(function(ext) { return token(ext[0], count(ext[1])) }))
}

function repoFacts(repo) {
  var tokens = [token("git", "tracked " + count(repo.tracked))]
  if (repo.rules.length) tokens.push(token("rule", repo.rules.join(", ")))
  return tokens
}

function notProposed(np, home) {
  var tokens = []
  if (np.no_kind && np.no_kind.length) tokens.push(token("no-kind", np.no_kind.map(function(path) { return displayPath(path, home) }).join(", ")))
  ;["dot", "heavy", "dataset"].forEach(function(key) {
    if (np[key]) tokens.push(token(key, count(np[key]) + " dirs"))
  })
  return tokens.length ? [token("not proposed", "")].concat(tokens) : []
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

function totals(rows, rates, device) {
  var result = {files: 0, bytes: 0, seconds: 0}
  ;(rows || []).forEach(function(row) {
    if (!row.checked || !row.counts) return
    KINDS.forEach(function(kind) { result.files += row.counts[kind] || 0 })
    var estimated = estimate(row.counts, rates, device)
    result.bytes += estimated.bytes
    result.seconds += estimated.seconds
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
  return {count: count(p.done), facts: facts, side: side, spinning: !!p.running, fraction: fraction(p.done, total)}
}

// Step 3 failure line: the daemon's error sentence, else `exit N` from a finished run that failed.
// "" while the run is fine.
function indexFailure(progress, error) {
  if (error) return error
  if (progress && !progress.running && progress.exit != null && progress.exit !== 0) return "exit " + progress.exit
  return ""
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

function chordKeys(chord) {
  return chord.split("+").map(function(key) {
    var part = key.trim()
    return ["SUPER", "SHIFT", "CTRL", "ALT"].indexOf(part) < 0 ? part : part.charAt(0) + part.slice(1).toLowerCase()
  })
}

function shortcutLine(checks, chosen) {
  var result = checks[chosen]
  if (!result) return {tone: "busy", text: "Checking your bindings"}
  if (result === "ours") return {tone: "ok", text: "Bound by omafind."}
  if (result.conflict) return {tone: "warn", text: result.conflict}
  var others = CHORDS.filter(function(chord) { return chord !== chosen && checks[chord] === "free" })
  return {tone: "ok", text: "Free." + (others.length ? " Also free: " + others.map(function(chord) { return chordKeys(chord).join(" ") }).join(", ") + "." : "")}
}

function nextChord(checks, current) {
  var start = CHORDS.indexOf(current)
  for (var offset = 1; offset <= CHORDS.length; offset++) {
    var chord = CHORDS[(start + offset) % CHORDS.length]
    if (checks[chord] === "free" || checks[chord] === "ours") return chord
  }
  return current
}
