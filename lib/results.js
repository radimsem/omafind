.pragma library
.import "format.js" as Format

// QML supplies import namespaces; the Node loader shares one global context.
var F = typeof Format !== "undefined" ? Format : this

function sectionTitle(kind) {
  return {image: "Images", video: "Video", audio: "Audio", pdf: "PDFs", text: "Documents", code: "Code"}[kind]
}

function badge(item) {
  return item.offline ? "offline" : F.at(item) || ""
}

function group(items, opts) {
  var sections = []
  var byKind = {}
  var weak = []
  var rows = []
  for (var i = 0; i < items.length; i++) {
    var item = items[i]
    if (item.weak === true) {
      weak.push(item)
      continue
    }
    var section = byKind[item.kind]
    if (!section) {
      section = {kind: item.kind, title: sectionTitle(item.kind), count: 0, items: []}
      byKind[item.kind] = section
      sections.push(section)
    }
    section.items.push(item)
    section.count += 1
  }
  for (var j = 0; j < sections.length; j++) {
    var current = sections[j]
    rows.push({type: "header", key: "h:" + current.kind, kind: current.kind,
      title: current.title, count: current.count})
    for (var k = 0; k < current.items.length; k++) {
      var hit = current.items[k]
      rows.push({type: "item", key: hit.id, item: hit, badge: badge(hit), weak: false})
    }
  }
  if (opts && opts.expanded) {
    for (var w = 0; w < weak.length; w++) {
      rows.push({type: "item", key: weak[w].id, item: weak[w], badge: badge(weak[w]), weak: true})
    }
  } else if (weak.length) {
    rows.push({type: "weak", key: "weak", count: weak.length})
  }
  return {rows: rows, sections: sections, weakCount: weak.length}
}

function merge(current, reply, latestSeq) {
  if (reply.seq !== latestSeq) return current
  if (reply.t === "error") return reply
  if (current && current.seq === reply.seq && current.legs && current.legs.indexOf("meaning") >= 0
      && (!reply.legs || reply.legs.indexOf("meaning") < 0)) return current
  return reply
}

function selectable(rows) {
  var indexes = []
  for (var i = 0; i < rows.length; i++) {
    if (rows[i].type === "item" || rows[i].type === "weak") indexes.push(i)
  }
  return indexes
}

function firstSelection(rows) {
  var indexes = selectable(rows)
  return indexes.length ? indexes[0] : -1
}

function move(rows, index, delta) {
  var indexes = selectable(rows)
  if (!indexes.length) return -1
  if (delta > 0) {
    for (var i = 0; i < indexes.length; i++) {
      if (indexes[i] > index) return indexes[i]
    }
    return indexes[indexes.length - 1]
  }
  for (var j = indexes.length - 1; j >= 0; j--) {
    if (indexes[j] < index) return indexes[j]
  }
  return indexes[0]
}

function selectionAfterRegroup(oldRows, oldIndex, newRows) {
  var old = oldRows[oldIndex]
  if (old) {
    var indexes = selectable(newRows)
    for (var i = 0; i < indexes.length; i++) {
      if (newRows[indexes[i]].key === old.key) return indexes[i]
    }
  }
  return firstSelection(newRows)
}

function footerLeft(view) {
  if (view.phase === "words") return "Matching words…"
  var reply = view.reply || {}
  var total = reply.total || 0
  var text = F.count(total) + (total === 1 ? " result" : " results")
  if (reply.degraded != null) return text + " · keyword matches only"
  if (view.prefix === "code" || view.prefix === "code:") text += " in your code"
  return text + (reply.weaker ? " · " + F.count(reply.weaker) + " weaker" : "")
}

function footerIdle(status) {
  var text = F.count(status.files) + " files · watching " + F.count(status.roots)
    + (status.roots === 1 ? " folder" : " folders")
  for (var i = 0; i < status.offline.length; i++) text += " · " + status.offline[i] + " offline"
  var progress = status.done < status.total
    ? {text: "Indexing " + F.count(status.done) + " of " + F.count(status.total),
      fraction: status.done / status.total} : null
  return {text: text, progress: progress}
}
