import QtQuick
import Quickshell
import qs.Commons
import ".." as Plugin
import "../lib/setup.js" as Setup
import "../lib/ledger.js" as Ledger
import "../lib/tree.js" as Tree

// Step 2 (board Discover, M3 steps 2 and 4): the folder table with sections, left-out ledgers,
// repositories and "Add folder", then the totals footer. Selection lives here for the session.
FocusScope {
  id: root

  property var service: null

  // Session state. Maps are replaced, never mutated, so bindings see each change.
  property var checked: ({})
  property var excludes: ({})
  // Root path to the root-relative folders searched inside a left-out one (tree.js `chosen`).
  property var chosenIn: ({})
  property var repoChecked: ({})
  property var openLedgers: ({})
  property var added: []
  property var pendingAdds: []
  property var requested: ({})
  // The exclude the last tree commit added, drawn as just added in its ledger.
  property var hot: ({root: "", path: ""})
  property bool picking: false
  property var firstRow: null

  signal backRequested()
  signal treeRequested(string root)

  readonly property var discover: service ? service.discover : null
  readonly property string home: discover && discover.home ? discover.home : (Quickshell.env("HOME") || "")
  readonly property var rates: discover ? discover.rates : null
  readonly property string device: discover && discover.device ? discover.device : "gpu"
  readonly property var candidates: discover && discover.candidates ? discover.candidates : []
  readonly property var homeRows: candidates.filter(c => c.section === "home")
  readonly property var elsewhereRows: candidates.filter(c => c.section !== "home").concat(added)
  readonly property var allRows: homeRows.concat(elsewhereRows)
  readonly property var repos: discover && discover.repos ? discover.repos : []
  readonly property var trees: service ? service.trees : ({})
  readonly property var ledgers: {
    var out = {}
    for (var i = 0; i < allRows.length; i++) out[allRows[i].path] = ledgerFor(allRows[i])
    return out
  }
  readonly property var totals: Setup.totals(allRows.map(c => ({checked: isChecked(c), counts: ledgers[c.path].kept})), rates, device)
  readonly property bool anyChecked: allRows.some(c => isChecked(c)) || repos.some(r => !!repoChecked[r.path])
  readonly property bool scanDone: !!discover && !!service && !service.scanning

  function focusFirst() {
    if (firstRow) firstRow.focusCheck()
    else if (start.enabled) start.forceActiveFocus()
    else back.forceActiveFocus()
  }

  // The board bolds the count of `selected`, not the word "files".
  function footerFacts(tokens) {
    return tokens.map(t => t.k === "selected" && t.tone === "strong"
      ? {k: t.k, v: String(t.v).replace(/^([\d,]+)/, "<b>$1</b>"), tone: "plain"} : t)
  }

  function baseName(path) {
    var parts = String(path).split("/")
    return parts[parts.length - 1] || path
  }

  function isChecked(c) {
    return checked[c.path] !== undefined ? checked[c.path] : !!c.checked
  }

  function ruleOf(c, path) {
    var entries = c.left_out || []
    for (var i = 0; i < entries.length; i++)
      if (entries[i].path === path) return entries[i].rule
    return "user"
  }

  function excludesFor(c) {
    if (excludes[c.path] !== undefined) return excludes[c.path]
    return (c.excludes || []).map(path => ({path: path, rule: ruleOf(c, path)}))
  }

  function chosenFor(c) {
    return chosenIn[c.path] || []
  }

  // Before the root's discover_tree arrives, the ledger comes from the candidate's own left_out.
  function initialLedger(c, list) {
    var kinds = Setup.KINDS
    var keep = list.map(e => e.path)
    var entries = []
    var secrets = null
    var leftOut = {total: 0}
    kinds.forEach(k => leftOut[k] = 0)
    var source = c.left_out || []
    for (var i = 0; i < source.length; i++) {
      var e = source[i]
      if (e.path === "**") secrets = {counts: e.counts, files: e.files, evidence: e.evidence}
      else if (keep.indexOf(e.path) < 0) continue
      entries.push({path: e.path, rule: e.rule, counts: e.counts, files: e.files, evidence: e.evidence, added: null})
      kinds.forEach(k => leftOut[k] += e.counts[k] || 0)
      leftOut.total += e.files || 0
    }
    var found = {total: c.found}
    var kept = {total: c.found - leftOut.total}
    kinds.forEach(k => {
      found[k] = c.found_counts ? c.found_counts[k] : c.counts[k]
      kept[k] = found[k] - leftOut[k]
    })
    return {found: found, kept: kept, leftOut: leftOut, entries: entries, secrets: secrets,
      dirs: entries.filter(e => e.rule !== "secrets").length}
  }

  function ledgerFor(c) {
    var tree = trees ? trees[c.path] : null
    return tree ? Tree.ledger(tree, excludesFor(c), chosenFor(c), Ledger.compute) : initialLedger(c, excludesFor(c))
  }

  function setMap(name, key, value) {
    var next = Object.assign({}, root[name])
    next[key] = value
    root[name] = next
  }

  function toggleRoot(c) {
    setMap("checked", c.path, !isChecked(c))
    hot = {root: "", path: ""}
  }

  function toggleLedger(c) {
    var open = !openLedgers[c.path]
    setMap("openLedgers", c.path, open)
    if (open) requestTree(c.path)
  }

  function openLedger(path) {
    setMap("openLedgers", path, true)
    requestTree(path)
  }

  function requestTree(path) {
    if (!service || (trees && trees[path]) || requested[path]) return
    setMap("requested", path, true)
    service.requestTree(path)
  }

  // Ask for the tree of every checked root that leaves something out, so edits recompute.
  function prefetch() {
    for (var i = 0; i < allRows.length; i++) {
      var c = allRows[i]
      if (isChecked(c) && (c.left_out || []).length) requestTree(c.path)
    }
  }

  function includeAgain(c, path) {
    setMap("excludes", c.path, Ledger.removeExclude(excludesFor(c), path))
    setMap("chosenIn", c.path, chosenFor(c).filter(folder => !Tree.isInside(folder, path)))
    hot = {root: "", path: ""}
  }

  // Called by the tree's "Done" with its draft excludes and chosen folders.
  function commitExcludes(path, list, chosen) {
    var c = allRows.find(row => row.path === path)
    if (!c) return
    var before = excludesFor(c).map(e => e.path)
    var fresh = list.filter(e => e.rule === "user" && before.indexOf(e.path) < 0)
    setMap("excludes", path, list)
    setMap("chosenIn", path, chosen || [])
    setMap("openLedgers", path, true)
    hot = fresh.length ? {root: path, path: fresh[fresh.length - 1].path} : {root: "", path: ""}
  }

  function volumeOf(path) {
    var best = null
    for (var i = 0; i < allRows.length; i++) {
      var c = allRows[i]
      if ((path === c.path || path.indexOf(c.path + "/") === 0) && (!best || c.path.length > best.path.length)) best = c
    }
    return best && best.volume ? best.volume : ""
  }

  function startIndexing() {
    var chosen = []
    var skipped = []
    for (var i = 0; i < allRows.length; i++) {
      var c = allRows[i]
      if (!isChecked(c)) continue
      chosen.push(c.path)
      chosenFor(c).forEach(folder => chosen.push(c.path + "/" + folder))
      excludesFor(c).forEach(e => {
        if (e.rule !== "secrets") skipped.push(e.path === "" ? c.path : c.path + "/" + e.path)
      })
    }
    var codeRoots = repos.filter(r => !!repoChecked[r.path]).map(r => r.path)
    service.startIndexing(Tree.toRoots(chosen, skipped, volumeOf), codeRoots)
  }

  function addFolder(path) {
    picking = false
    pendingAdds = pendingAdds.concat([path])
    if (service) service.requestTree(path)
  }

  // Keeps the focused control in view when Tab moves past the visible rows.
  function reveal(item) {
    if (!item || !flick.contentItem) return
    var p = item.mapToItem(flick.contentItem, 0, 0)
    if (p.y < flick.contentY) flick.contentY = Math.max(0, p.y - Style.space(8))
    else if (p.y + item.height > flick.contentY + flick.height)
      flick.contentY = Math.min(flick.contentHeight - flick.height, p.y + item.height - flick.height + Style.space(8))
  }

  Connections {
    target: root.service
    ignoreUnknownSignals: true
    // discover_tree errors carry no root, so every pending add and tree request is dropped and can
    // be retried.
    function onSetupFailed(forType, reason) {
      if (forType !== "discover_tree") return
      root.pendingAdds = []
      root.requested = {}
    }
    function onTreeReceived(reply) {
      if (!reply || !reply.candidate) return
      var index = root.pendingAdds.indexOf(reply.root)
      if (index < 0) index = root.pendingAdds.indexOf(reply.abs)
      if (index < 0) return
      root.pendingAdds = root.pendingAdds.filter((p, i) => i !== index)
      var path = reply.abs || reply.candidate.path
      if (!root.allRows.some(c => c.path === path)) {
        var row = Object.assign({}, reply.candidate)
        row.path = path
        row.section = "elsewhere"
        row.checked = true
        root.added = root.added.concat([row])
      }
      root.setMap("checked", path, true)
    }
  }

  Connections {
    target: root.Window.window
    ignoreUnknownSignals: true
    function onActiveFocusItemChanged() {
      var item = root.Window.activeFocusItem
      for (var p = item; p; p = p.parent) if (p === flick.contentItem) return root.reveal(item)
    }
  }

  component SectionLabel: Item {
    id: section
    property string title: ""
    property string sub: ""
    property bool first: false
    width: parent ? parent.width : 0
    height: (first ? Style.space(10) : Style.space(14)) + label.implicitHeight + Style.space(4)

    Text {
      id: label
      x: Plugin.Tokens.tablePadding
      anchors.bottom: parent.bottom
      anchors.bottomMargin: Style.space(4)
      text: section.title
      textFormat: Text.PlainText
      color: Plugin.Tokens.dim
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      font.capitalization: Font.AllUppercase
      font.letterSpacing: Style.font.bodySmall * Plugin.Tokens.tracking
    }

    Text {
      anchors.right: parent.right
      anchors.rightMargin: Plugin.Tokens.tablePadding
      anchors.baseline: label.baseline
      text: section.sub
      textFormat: Text.PlainText
      color: Plugin.Tokens.dim
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      font.capitalization: Font.AllUppercase
      font.letterSpacing: Style.font.bodySmall * Plugin.Tokens.tracking
    }
  }

  // A root and its ledger. A Component, not an inline component, so it can reach this file's ids.
  Component {
    id: rootRowComponent

    Column {
      id: rootRow
      required property var modelData
      readonly property var c: modelData
      readonly property var ledger: root.ledgers[c.path] || root.initialLedger(c, [])
      readonly property int entryCount: ledger.entries.length
      readonly property bool open: !!root.openLedgers[c.path]
      readonly property var estimate: Setup.estimate(ledger.kept, root.rates, root.device)
      width: parent ? parent.width : 0

      function focusCheck() {
        row.focusCheck()
      }

      FolderRow {
        id: row
        objectName: "omafindFolderRow"
        width: parent.width
        table: header
        path: rootRow.c.path
        check: root.isChecked(rootRow.c) ? "on" : "off"
        checkLabel: "Include " + root.baseName(rootRow.c.path)
        name: Setup.displayPath(rootRow.c.path, root.home)
        facts: Setup.rowFacts(rootRow.c, Ledger.summary(rootRow.ledger))
        caret: rootRow.entryCount > 0 ? (rootRow.open ? "open" : "closed") : ""
        cells: Setup.KINDS.map(k => ({n: rootRow.ledger.kept[k] || 0, cut: false}))
        indexText: rootRow.estimate ? Setup.mb(rootRow.estimate.bytes) : ""
        timeText: rootRow.estimate ? Setup.minutes(rootRow.estimate.seconds) : ""
        action: "filter"
        actionActive: rootRow.open
        actionLabel: "Add an exclude to " + root.baseName(rootRow.c.path)
        fill: root.isChecked(rootRow.c) ? "on" : ""
        onToggled: root.toggleRoot(rootRow.c)
        onActionClicked: root.toggleLedger(rootRow.c)
        onCaretClicked: root.toggleLedger(rootRow.c)
      }

      LeftOutLedger {
        width: parent.width
        table: header
        ledger: rootRow.ledger
        open: rootRow.open
        prefix: Setup.displayPath(rootRow.c.path, root.home) + "/"
        hotPath: root.hot.root === rootRow.c.path ? root.hot.path : ""
        onIncludeAgain: path => root.includeAgain(rootRow.c, path)
        onLeaveOutRequested: root.treeRequested(rootRow.c.path)
      }
    }
  }

  // Height the page needs to show every row and the footer without scrolling; SetupView grows the
  // card to it and Overlay clamps the card to the screen.
  readonly property real contentNeed: header.height + table.implicitHeight + Plugin.Tokens.setupGap
    + footer.implicitHeight

  FolderTable {
    id: header
    width: parent.width
  }

  Flickable {
    id: flick
    anchors.top: header.bottom
    anchors.bottom: footer.top
    anchors.bottomMargin: Plugin.Tokens.setupGap
    width: parent.width
    contentHeight: table.implicitHeight
    clip: true
    boundsBehavior: Flickable.StopAtBounds

    Column {
      id: table
      width: flick.width

      SectionLabel {
        first: true
        title: "Home folders"
        sub: "XDG, checked when they hold files"
      }

      Repeater {
        model: root.homeRows
        delegate: rootRowComponent
        onItemAdded: (index, item) => { if (index === 0) root.firstRow = item }
      }

      SectionLabel {
        visible: root.elsewhereRows.length > 0
        title: "Found elsewhere"
        sub: "unchecked until you choose"
      }

      Repeater {
        model: root.elsewhereRows
        delegate: rootRowComponent
      }

      SectionLabel {
        visible: root.repos.length > 0
        title: "Code repositories"
        sub: "separate code index, searched only with code:"
      }

      Repeater {
        model: root.repos

        delegate: FolderRow {
          required property var modelData
          width: table.width
          table: header
          path: modelData.path
          check: root.repoChecked[modelData.path] ? "on" : "off"
          checkLabel: "Index code in " + root.baseName(modelData.path)
          name: Setup.displayPath(modelData.path, root.home)
          facts: Setup.repoFacts(modelData)
          dash: true
          indexText: Setup.mb(modelData.index_bytes)
          timeText: Setup.minutes(modelData.seconds)
          fill: root.repoChecked[modelData.path] ? "on" : ""
          onToggled: root.setMap("repoChecked", modelData.path, !root.repoChecked[modelData.path])
        }
      }

      Item {
        width: parent.width
        height: Style.space(12) + Math.max(addFolder.height, picker.visible ? picker.implicitHeight : 0)

        Row {
          visible: !root.picking
          x: Plugin.Tokens.tablePadding
          y: Style.space(12)
          spacing: Style.space(8)

          ActionButton {
            id: addFolder
            objectName: "omafindAddFolder"
            text: "Add folder"
            icon: "plus"
            focusable: true
            buttonHeight: Style.space(28)
            onClicked: {
              root.picking = true
              picker.reset()
              Qt.callLater(picker.focusField)
            }
          }

          Row {
            anchors.verticalCenter: parent.verticalCenter
            leftPadding: Style.space(6)
            spacing: Style.space(8)

            Spinner {
              anchors.verticalCenter: parent.verticalCenter
              visible: root.pendingAdds.length > 0
              running: visible
            }

            SetupFacts {
              anchors.verticalCenter: parent.verticalCenter
              tokens: root.discover ? Setup.notProposed(root.discover.not_proposed, root.home) : []
            }
          }
        }

        PathField {
          id: picker
          visible: root.picking
          x: Plugin.Tokens.tablePadding
          y: Style.space(12)
          width: parent.width - 2 * x
          service: root.service
          onAdded: path => root.addFolder(path)
          onCancelled: {
            root.picking = false
            addFolder.forceActiveFocus()
          }
        }
      }
    }
  }

  Column {
    id: footer
    anchors.bottom: parent.bottom
    width: parent.width
    spacing: Plugin.Tokens.setupGap

    Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }

    Text {
      visible: !!root.service && root.service.setupError !== ""
      width: parent.width
      wrapMode: Text.Wrap
      text: root.service ? root.service.setupError : ""
      textFormat: Text.PlainText
      color: Color.urgent
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }

    Item {
      width: parent.width
      height: Style.space(32)

      SetupFacts {
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        width: Math.min(implicitWidth, parent.width - buttons.width - Style.space(8))
        fontSize: Style.font.body
        gap: Style.space(18)
        tokens: root.discover ? root.footerFacts(Setup.totalFacts(root.totals, root.device)) : []
      }

      Row {
        id: buttons
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(8)

        ActionButton {
          id: back
          objectName: "omafindSetupBack"
          text: "Back"
          focusable: true
          onClicked: root.backRequested()
        }

        ActionButton {
          id: start
          objectName: "omafindSetupStart"
          text: "Start indexing"
          primary: true
          neutral: true
          focusable: true
          enabled: root.scanDone && root.anyChecked && !root.service.indexPending
          onClicked: root.startIndexing()
        }
      }
    }
  }
}
