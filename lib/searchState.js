.pragma library
.import "results.js" as Results
.import "format.js" as Format

var R = typeof Results !== "undefined" ? Results : this
var F = typeof Format !== "undefined" ? Format : this
var prefixes = ["img:", "pdf:", "doc:", "vid:", "aud:", "code:"]
var wordsDelay = 50
var meaningDelay = 200

function parse(query) {
  var kinds = ["image", "pdf", "text", "video", "audio", "code"]
  for (var i = 0; i < prefixes.length; i++) {
    if (query.indexOf(prefixes[i]) === 0) {
      return {prefix: prefixes[i], kind: kinds[i], text: query.slice(prefixes[i].length).replace(/^\s+/, ""),
        code: kinds[i] === "code"}
    }
  }
  return {prefix: null, kind: null, text: query, code: false}
}

function initial() {
  return {query: "", seq: 0, phase: "idle", sentWords: 0, sentMeaning: 0, reply: null, started: 0}
}

function reduce(state, event) {
  var next = {query: state.query, seq: state.seq, phase: state.phase, sentWords: state.sentWords,
    sentMeaning: state.sentMeaning, reply: state.reply, started: state.started}
  var send = null
  if (event.type === "typed") {
    next.query = event.query
    next.started = event.now
    if (!parse(event.query).text.trim()) {
      next.phase = "idle"
      next.reply = null
    } else {
      next.seq += 1
      next.phase = "words"
    }
  } else if (event.type === "words-due" || event.type === "meaning-due") {
    var parsed = parse(state.query)
    var meaning = event.type === "meaning-due"
    var due = event.now - state.started >= (meaning ? meaningDelay : wordsDelay)
    var unsent = meaning ? state.sentMeaning !== state.seq
      : state.sentWords !== state.seq && state.sentMeaning !== state.seq
    if (parsed.text.trim() && due && unsent) {
      send = {t: "search", seq: state.seq, q: parsed.text,
        legs: meaning ? ["words", "meaning"] : ["words"]}
      if (parsed.kind) send.kinds = [parsed.kind]
      if (meaning) next.sentMeaning = state.seq
      else next.sentWords = state.seq
    }
  } else if (event.type === "reply" && parse(state.query).text.trim()) {
    var reply = R.merge(state.reply, event.reply, state.seq)
    if (reply !== state.reply) {
      var kind = parse(state.query).kind
      if (kind && reply.items) {
        var filtered = {}
        for (var key in reply) filtered[key] = reply[key]
        filtered.items = reply.items.filter(function(item) { return item.kind === kind })
        reply = filtered
      }
      next.reply = reply
      next.phase = reply.degraded != null ? "degraded"
        : reply.t === "error" || (reply.legs && reply.legs.indexOf("meaning") >= 0) ? "done" : "words"
    }
  }
  return {state: next, send: send}
}

function status(state, reply) {
  if (!parse(state.query).text.trim()) return {text: "ready", spinner: false}
  var result = reply || state.reply
  if (state.phase === "words" && result && result.seq === state.seq)
    return {text: "matching by meaning", spinner: true}
  return {text: (state.phase === "done" || state.phase === "degraded") && result && result.ms
    ? Math.round(result.ms.total) + " ms" : "", spinner: false}
}

function lastWordPrefix(query) {
  // Punctuation boundaries keep non-Latin words intact without ASCII-only \w.
  var match = parse(query).text.match(/([^\s!-\/:-@\[-\^`{-~\u2000-\u206f\u3000-\u303f]+)$/)
  return match ? match[1] : ""
}

function highlight(text, words, partialLast) {
  var runs = []
  var pattern = /[^\s!-\/:-@\[-\^`{-~\u2000-\u206f\u3000-\u303f]+/g
  var terms = words.map(function(word) { return word.toLowerCase() })
  var partial = (partialLast || "").toLowerCase()
  var cursor = 0
  var match
  while ((match = pattern.exec(text)) !== null) {
    var word = match[0].toLowerCase()
    var length = terms.indexOf(word) >= 0 ? match[0].length
      : partial && word.indexOf(partial) === 0 ? partial.length : 0
    if (!length) continue
    if (match.index > cursor) runs.push({t: text.slice(cursor, match.index), m: false})
    runs.push({t: text.slice(match.index, match.index + length), m: true})
    cursor = match.index + length
  }
  if (cursor < text.length) runs.push({t: text.slice(cursor), m: false})
  return F.snippetRuns(runs)
}
