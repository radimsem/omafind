import QtQuick
import qs.Commons
import "../lib/setup.js" as Setup
import "../lib/tree.js" as Tree

// The lazy folder tree of the Folders step and the drive dialog. Top rows come from `folders`;
// a row's children load on its first expand through Service.requestChildren and stay cached
// there, so collapsing only removes rows from the model.
FocusScope {
  id: root

  property var service: null
  property var table: null
  // Top rows: [{path, name, xdg, repo, hasChildren, volume}].
  property var folders: []
  property var choices: Tree.initial([])
  property string home: ""
  property var rates: null
  property string device: "gpu"
  // A drive's mount: its rows read "/name" instead of "~/name".
  property string mount: ""
  property bool locked: false
  // Drives mounted below a walked root; see Tree.value.
  property var mounts: []

  signal choicesEdited(var choices)

  property var expanded: ({})
  // Path -> folder row from `folders` or a children reply.
  property var meta: ({})

  readonly property var counts: service ? service.discoverCounts : ({})
  readonly property var walks: service ? service.walks : ({})
  readonly property var datasets: service ? service.datasets : ({})
  readonly property var cached: service ? service.childFolders : ({})
  readonly property int count: list.count
  readonly property var totals: {
    var out = {files: 0, bytes: 0, seconds: 0}
    var outer = folders.filter(folder => !folders.some(other =>
      other.path !== folder.path && Tree.isInside(folder.path, other.path)))
    for (var i = 0; i < outer.length; i++) {
      var kept = Tree.value(outer[i].path, choices, countOf, mounts)
      if (!kept) continue
      var estimate = Setup.estimate(kept, rates, device)
      Setup.KINDS.forEach(kind => out.files += kept[kind])
      out.bytes += estimate.bytes
      out.seconds += estimate.seconds
    }
    return out
  }

  function focusFirst() {
    if (!list.count) return false
    list.positionViewAtBeginning()
    var first = list.itemAtIndex(0)
    if (!first) return false
    first.focusCheck()
    return true
  }

  function remember(rows) {
    var next = Object.assign({}, meta)
    rows.forEach(row => next[row.path] = row)
    meta = next
  }

  function walkFor(path) {
    var best = ""
    for (var walkRoot in walks) if (Tree.isInside(path, walkRoot) && walkRoot.length > best.length) best = walkRoot
    return best ? walks[best] : null
  }

  // Rolled-up counts, or null while the walk has not reached the folder. A finished walk
  // reports nothing for a folder without indexable files, which is zero.
  function countOf(path) {
    if (counts[path]) return counts[path]
    var walk = walkFor(path)
    return walk && walk.done ? {text: 0, pdf: 0, image: 0, video: 0, audio: 0} : null
  }

  function evidenceOf(path) {
    return datasets[path] || (meta[path] && meta[path].evidence) || null
  }

  function label(row, depth) {
    if (depth > 0) return row.name || ""
    if (mount) return row.path.slice(mount.replace(/\/$/, "").length) || "/"
    return Setup.displayPath(row.path, home)
  }

  function indexOf(path) {
    for (var i = 0; i < rows.count; i++) if (rows.get(i).path === path) return i
    return -1
  }

  function insert(index, path, depth) {
    var reply = cached[path]
    var dirs = reply ? reply.dirs : []
    remember(dirs)
    var at = index + 1
    for (var i = 0; i < dirs.length; i++) {
      rows.insert(at, {path: dirs[i].path, depth: depth + 1})
      var before = rows.count
      if (expanded[dirs[i].path]) {
        if (cached[dirs[i].path] && !cached[dirs[i].path].error) insert(at, dirs[i].path, depth + 1)
        else if (!cached[dirs[i].path] && service) service.requestChildren(dirs[i].path)
      }
      at += 1 + rows.count - before
    }
  }

  function toggle(index) {
    if (index < 0 || index >= rows.count) return
    var row = rows.get(index)
    var path = row.path
    var depth = row.depth
    var next = Object.assign({}, expanded)
    if (expanded[path]) {
      var end = index + 1
      while (end < rows.count && rows.get(end).depth > depth) end++
      if (end > index + 1) rows.remove(index + 1, end - index - 1)
      delete next[path]
      expanded = next
      return
    }
    next[path] = true
    expanded = next
    if (cached[path] && !cached[path].error) insert(index, path, depth)
    else if (service) service.requestChildren(path)
  }

  function reload() {
    remember(folders)
    var next = {}
    for (var path in expanded) {
      if (!folders.some(folder => Tree.isInside(path, folder.path))) continue
      var parent = cached[Tree.parent(path)]
      if (parent && !parent.error && !parent.dirs.some(dir => dir.path === path)) continue
      next[path] = true
    }
    expanded = next
    rows.clear()
    folders.forEach(folder => {
      var index = rows.count
      rows.append({path: folder.path, depth: 0})
      if (!expanded[folder.path]) return
      if (cached[folder.path] && !cached[folder.path].error) insert(index, folder.path, 0)
      else if (!cached[folder.path] && service) service.requestChildren(folder.path)
    })
  }

  // Inserts the children of expanded rows whose reply just arrived, so a reply never rebuilds
  // the list and the focused row survives.
  function fill() {
    for (var i = 0; i < rows.count; i++) {
      var path = rows.get(i).path
      var depth = rows.get(i).depth
      if (!expanded[path] || !cached[path] || cached[path].error) continue
      if (i + 1 < rows.count && rows.get(i + 1).depth > depth) continue
      insert(i, path, depth)
    }
  }

  onFoldersChanged: reload()
  onCachedChanged: fill()
  Component.onCompleted: reload()

  ListModel { id: rows }

  ListView {
    id: list
    anchors.fill: parent
    clip: true
    model: rows
    boundsBehavior: Flickable.StopAtBounds
    keyNavigationEnabled: false

    delegate: FolderRow {
      id: row
      required path
      required depth
      required property int index
      readonly property var info: root.meta[path] || ({})
      readonly property var found: root.countOf(path)
      readonly property var evidence: root.evidenceOf(path)
      readonly property var kept: Tree.value(path, root.choices, root.countOf, root.mounts)
      readonly property var shown: check === "off" ? found : kept
      readonly property var estimate: check !== "off" && kept ? Setup.estimate(kept, root.rates, root.device) : null
      objectName: "omafindFolderRow"
      width: ListView.view.width
      table: root.table
      enabled: !root.locked
      check: Tree.mark(path, root.choices)
      checkLabel: "Include " + (info.name || path)
      twisty: info.hasChildren ? (root.expanded[path] ? "open" : "closed") : "leaf"
      name: root.label(info, depth)
      rule: evidence ? "dataset" : info.repo ? "repo" : ""
      facts: root.cached[path] && root.cached[path].error
        ? [Setup.token("error", root.cached[path].error, "fail")]
        : evidence ? Setup.datasetFacts(evidence) : []
      dash: !shown
      pending: !found
      cells: shown ? Setup.KINDS.map(kind => ({n: shown[kind] || 0, cut: false})) : []
      indexText: estimate ? Setup.mb(estimate.bytes) : ""
      timeText: estimate ? Setup.minutes(estimate.seconds) : ""
      action: info.repo ? "code" : ""
      actionActive: root.choices.code.indexOf(path) >= 0
      actionLabel: "Index the code in " + (info.name || path)
      fill: check === "on" ? "on" : ""
      onToggled: root.choicesEdited(Tree.click(root.choices, path))
      onTwistyClicked: root.toggle(index)
      onActionClicked: root.choicesEdited(Tree.toggleCode(root.choices, path))
      onFocusedChanged: if (focused) ListView.view.positionViewAtIndex(index, ListView.Contain)
      Keys.onRightPressed: if (info.hasChildren && !root.expanded[path]) root.toggle(index)
      Keys.onLeftPressed: if (root.expanded[path]) root.toggle(index)
    }
  }
}
