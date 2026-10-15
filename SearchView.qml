import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import "." as Plugin
import "ui" as Parts
import "lib/keys.js" as KeyMap
import "lib/setup.js" as Setup
import "lib/results.js" as Results
import "lib/searchState.js" as SearchState
import "lib/Update.js" as Update
import "lib/volumes.js" as Volumes

// The search overlay body: query row, banner, result list, preview and footer.
Item {
  id: root

  property var service: null
  property var search: SearchState.initial()
  property bool expanded: false
  property bool progressOpen: false
  property var rows: []
  property int selectedIndex: -1
  // True once the user moves the selection, so a re-rank keeps it on its row instead of the top hit.
  property bool userMoved: false
  property int shownSeq: -1
  property var preview: null
  property var pending: null
  property string flash: ""
  property string editorCommand: "nvim"
  // M4: keys of files that landed while the list was open, marked for 2.8 s.
  property var freshKeys: []
  // The search sent again by refresh(): its seq, the items before it and the indexed count then.
  property var refreshFrom: null
  property int lastFiles: -1

  readonly property var parsed: SearchState.parse(search.query)
  readonly property bool idle: search.query.trim() === ""
  readonly property bool noText: parsed.text.trim() === ""
  readonly property var reply: search.reply
  readonly property var selectedRow: rows[selectedIndex] || null
  readonly property var selectedItem: selectedRow && selectedRow.type === "item" ? selectedRow.item : null
  readonly property string editorName: KeyMap.editorName(editorCommand)
  readonly property var connection: service ? service.connection : null
  readonly property bool daemonDown: !service || (!service.ready && !!connection
    && (connection.unit === "missing" || connection.failures > 0))
  // Set while Service.qml brings the daemon to the plugin's build (issue #16).
  readonly property var updateBanner: service && service.update ? Update.banner(service.update) : null
  readonly property string degradedReason: reply && reply.degraded ? String(reply.degraded)
    : service && service.warmFailure ? service.warmFailure : ""

  // The daemon sends either a phrase ("indexing in progress", "embedding model unavailable",
  // "the embedding server did not start") or the bare cause of a server failure.
  function degradedClause(reason) {
    if (/^(the embedding server|embedding model|indexing)/.test(reason)) return reason
    return "the embedding server did not start (" + reason + ")"
  }

  signal closeRequested()
  signal toastRequested(string title, var tokens, bool error)
  signal openStarted(var item, string how)

  function reset() {
    previewTimer.stop()
    wordsTimer.stop()
    meaningTimer.stop()
    player.stop()
    flash = ""
    expanded = false
    progressOpen = false
    userMoved = false
    shownSeq = -1
    freshTimer.stop()
    freshKeys = []
    refreshFrom = null
    preview = null
    search = SearchState.initial()
    rows = []
    selectedIndex = -1
    list.reset()
    query.setText("")
  }

  function stopPlayback() {
    player.stop()
  }

  function focusQuery() {
    query.input.forceActiveFocus()
  }

  function typed(text) {
    if (text === search.query) return
    var next = SearchState.reduce(search, {type: "typed", query: text, now: Date.now()})
    search = next.state
    expanded = false
    userMoved = false
    if (SearchState.parse(text).text.trim() === "") {
      wordsTimer.stop()
      meaningTimer.stop()
      rows = []
      selectedIndex = -1
      shownSeq = -1
      preview = null
      player.stop()
      list.reset()
      return
    }
    wordsTimer.restart()
    meaningTimer.restart()
  }

  function due(type) {
    var next = SearchState.reduce(search, {type: type, now: Date.now()})
    if (next.send && (!service || !service.send(next.send))) {
      next.state.sentWords = search.sentWords
      next.state.sentMeaning = search.sentMeaning
    }
    search = next.state
  }

  function received(message) {
    var next = SearchState.reduce(search, {type: "reply", reply: message})
    var changed = next.state.reply !== search.reply
    search = next.state
    if (changed && refreshFrom && message.seq === refreshFrom.seq && message.items) {
      var files = service && service.status ? service.status.files || 0 : refreshFrom.files
      var keys = Volumes.freshKeys(refreshFrom.items, message.items, refreshFrom.files, files)
      if (keys.length) {
        freshKeys = keys
        freshTimer.restart()
      }
    }
    if (changed) regroup()
  }

  // Sends the current query again without clearing the list, after new files land or a drive
  // reconciles. The reply re-ranks the rows in place.
  function refresh(files) {
    if (noText || !service) return
    var next = SearchState.reduce(search, {type: "typed", query: search.query, now: Date.now() - SearchState.meaningDelay})
    next.state.phase = search.phase
    next.state.reply = search.reply
    refreshFrom = {seq: next.state.seq, items: reply && reply.items ? reply.items : [], files: files}
    search = next.state
    due("meaning-due")
  }

  function regroup() {
    var result = reply && reply.items ? Results.group(reply.items, {expanded: expanded}).rows : []
    var index = -1
    var sameSet = reply && reply.seq === shownSeq
    var refreshed = !!reply && !!refreshFrom && reply.seq === refreshFrom.seq
    if ((sameSet || refreshed) && (userMoved || expanded)) index = Results.selectionAfterRegroup(rows, selectedIndex, result)
    else index = Results.firstSelection(result)
    shownSeq = reply ? reply.seq : -1
    rows = result
    selectedIndex = index
  }

  // Keep selection on the fold row in both states.
  function toggleWeak() {
    expanded = !expanded
    var result = Results.group(reply.items, {expanded: expanded}).rows
    var weakAt = -1
    for (var i = 0; i < result.length; i++) if (result[i].type === "weak") weakAt = i
    rows = result
    selectedIndex = weakAt >= 0 ? weakAt : Results.firstSelection(result)
    userMoved = true
  }

  function move(delta) {
    var next = Results.move(rows, selectedIndex, delta)
    if (next !== selectedIndex) {
      selectedIndex = next
      userMoved = true
    }
  }

  function jumpBy(steps) {
    var next = Results.jump(rows, selectedIndex, steps)
    if (next !== selectedIndex) {
      selectedIndex = next
      userMoved = true
    }
  }

  // One visible page of rows, less one row of overlap.
  function pageSize() {
    return Math.max(1, Math.floor(list.height / Plugin.Tokens.rowHeight) - 1)
  }

  function select(index) {
    if (index < 0) return
    selectedIndex = index
    userMoved = true
    focusQuery()
  }

  // Footer hints from lib/keys.js, with the editor named for code and the play label following playback.
  function hintsFor(row) {
    var hints = KeyMap.hints(row, row && row.type === "item" ? jumpFor(row.item) : null)
    if (!row || row.type !== "item") return hints
    var item = row.item
    for (var i = 0; i < hints.length; i++) {
      var hint = hints[i]
      if (hint.keys.length === 1 && hint.keys[0] === "Enter" && item.kind === "code")
        hint.label = hint.label.replace(/^open at line/, "open in " + editorName + " at line")
      if (hint.keys.join(" ") === "Ctrl Space" && player.playback.id === item.id)
        hint.label = player.playing ? "pause" : "resume"
    }
    return hints
  }

  // The preview names the line the opener jumps to, so labels use it once it arrives.
  function jumpFor(item) {
    if (!item || !preview || preview.id !== item.id) return null
    return item.kind === "text" || item.kind === "code" ? preview.jump : null
  }

  function folder(item) {
    var path = item.dir || ""
    var home = Quickshell.env("HOME") || ""
    if ((item.offline || item.drive) && item.label) return item.label + " · " + path
    if (home && (path === home || path.indexOf(home + "/") === 0)) return "~" + path.slice(home.length)
    return path
  }

  function markersFor(item) {
    if (!item || item.kind !== "video" || !reply || !reply.items) return []
    var total = item.info && item.info.duration ? item.info.duration : 0
    if (!total) return []
    var out = []
    for (var i = 0; i < reply.items.length; i++) {
      var other = reply.items[i]
      if (other.kind === "video" && other.path === item.path && other.loc != null)
        out.push(Math.max(0, Math.min(1, other.loc / total)))
    }
    return out
  }

  function act(how) {
    var item = selectedItem
    if (!item) return
    if (item.offline && how !== "copy") return
    if (how === "copy") {
      Quickshell.execDetached(["wl-copy", "--", item.path])
      toastRequested("Path copied", [{k: "path", v: folder(item) + "/" + item.name, tone: "plain"}], false)
      return
    }
    var message = {t: "open", id: item.id, how: how}
    var line = jumpFor(item)
    if (how === "open" && line != null) message.line = line
    if (pending || !service || !service.send(message)) return
    player.stop()
    flash = how === "open" ? "acc" : "sec"
    openStarted(item, how)
  }

  function toggleProgress() {
    progressOpen = !progressOpen
    if (progressOpen && service) service.requestProgress()
  }

  function handleKey(event) {
    // Close the popover before clearing the query or closing the overlay.
    if (progressOpen && event.key === Qt.Key_Escape) {
      progressOpen = false
      event.accepted = true
      return
    }
    if (event.key === Qt.Key_U && event.modifiers === Qt.ControlModifier) {
      query.setText("")
      event.accepted = true
      return
    }
    var action = KeyMap.action({key: event.key, text: event.text, modifiers: event.modifiers},
      {query: search.query, row: selectedRow, selection: query.input.selectedText !== ""})
    switch (action) {
    case "clear":
      query.setText("")
      break
    case "close":
      closeRequested()
      break
    case "up":
      move(-1)
      break
    case "down":
      move(1)
      break
    case "pageup":
      jumpBy(-pageSize())
      break
    case "pagedown":
      jumpBy(pageSize())
      break
    case "first":
      jumpBy(-Infinity)
      break
    case "last":
      jumpBy(Infinity)
      break
    case "open":
    case "reveal":
      act(action)
      break
    case "toggle-weak":
      toggleWeak()
      break
    case "play":
      player.toggle(selectedItem)
      break
    case "progress":
      toggleProgress()
      break
    case "copy":
      act("copy")
      break
    default:
      // Enter on an offline row and Ctrl Space off audio and video do nothing, and never reach the field.
      var enter = event.key === Qt.Key_Return || event.key === Qt.Key_Enter
      var ctrlSpace = event.key === Qt.Key_Space && (event.modifiers & Qt.ControlModifier)
      if (!enter && !ctrlSpace) return
    }
    event.accepted = true
  }

  readonly property string selectedId: selectedItem ? selectedItem.id : ""
  // Hit lines depend on the query, so a new seq asks again; the meaning leg of the same seq does not.
  readonly property string previewKey: selectedId ? selectedId + "@" + shownSeq : ""

  onSelectedIdChanged: {
    player.select(selectedId || null)
    if (preview && preview.id !== selectedId) preview = null
  }
  onPreviewKeyChanged: {
    if (previewKey) previewTimer.restart()
    else previewTimer.stop()
  }

  Connections {
    target: root.service
    ignoreUnknownSignals: true
    function onResultsReceived(message) { root.received(message) }
    function onPreviewReceived(message) {
      if (root.selectedItem && message.id === root.selectedItem.id) {
        root.preview = message
        if (message.editor) root.editorCommand = message.editor
      }
    }
    function onStatusReceived(message) {
      var files = typeof message.files === "number" ? message.files : -1
      var before = root.lastFiles
      root.lastFiles = files
      if (before >= 0 && files > before) root.refresh(before)
    }
    function onVolumesRefreshed() { root.refresh(root.lastFiles) }
    function onReadyChanged() {
      if (root.service && root.service.ready) {
        root.due("words-due")
        root.due("meaning-due")
      }
    }
  }

  // The editor that `omarchy-launch-editor` starts, until a preview reports it.
  FileView {
    path: (Quickshell.env("HOME") || "") + "/.local/state/omarchy/defaults/editor"
    printErrors: false
    onLoaded: {
      var first = text().split("\n")[0].trim().split(/\s+/)[0]
      if (first) root.editorCommand = first
    }
  }

  Timer {
    id: wordsTimer
    interval: SearchState.wordsDelay
    onTriggered: root.due("words-due")
  }

  Timer {
    id: meaningTimer
    interval: SearchState.meaningDelay
    onTriggered: root.due("meaning-due")
  }

  Timer {
    id: freshTimer
    interval: 2800
    onTriggered: root.freshKeys = []
  }

  Timer {
    id: previewTimer
    interval: 60
    onTriggered: {
      if (root.selectedItem && root.service)
        root.service.send({t: "preview", id: root.selectedItem.id, q: root.parsed.text})
    }
  }

  Parts.Player {
    id: player
    videoOutput: pane.videoOutput
  }

  Parts.QueryRow {
    id: query
    anchors.top: parent.top
    anchors.left: parent.left
    anchors.right: parent.right
    prefix: root.parsed.prefix || ""
    code: root.parsed.code
    status: SearchState.status(root.search, root.reply).text
    spinning: SearchState.status(root.search, root.reply).spinner
    onTextChanged: root.typed(text)
    onKeyPressed: event => root.handleKey(event)
  }

  Parts.Banner {
    id: banner
    anchors.top: query.bottom
    anchors.left: parent.left
    anchors.right: parent.right
    visible: !!root.updateBanner || root.daemonDown || root.degradedReason !== ""
      || (!!root.reply && root.reply.t === "error")
    height: visible ? implicitHeight : 0
    action: root.updateBanner ? root.updateBanner.action : "Retry"
    lead: root.updateBanner ? root.updateBanner.lead
      : root.daemonDown ? "" : root.degradedReason !== "" ? "Semantic search unavailable:" : ""
    text: root.updateBanner ? root.updateBanner.text
      : root.daemonDown ? "omafindd is not running. Run systemctl --user start omafind, then retry."
      : root.degradedReason !== "" ? root.degradedClause(root.degradedReason) + ". Showing keyword matches."
      : root.reply && root.reply.reason ? String(root.reply.reason) : ""
    onTriggered: {
      if (root.updateBanner) {
        root.service.retryUpdate()
      } else if (root.daemonDown) {
        if (root.service) {
          root.service.checkUnit()
          root.service.connectSocket()
        }
      } else if (root.degradedReason !== "") {
        root.service.warm()
      } else {
        root.search = SearchState.reduce(root.search, {type: "typed", query: root.search.query, now: Date.now()}).state
        meaningTimer.restart()
      }
    }
  }

  // Spec 6.5: indexing waits for disk space. The banner has no action; it clears on `resumed`.
  Parts.Banner {
    id: diskBanner
    readonly property var info: root.service && root.service.volumes ? Volumes.diskBanner(root.service.volumes) : null
    anchors.top: banner.bottom
    anchors.left: parent.left
    anchors.right: parent.right
    visible: !!info
    height: visible ? implicitHeight : 0
    lead: info ? info.title : ""
    tokens: info ? info.tokens.map(t => ({k: t.k, v: t.v, tone: "plain"})) : []
    text: info ? info.text : ""
    action: ""
  }

  Rectangle {
    id: separator
    anchors.top: diskBanner.bottom
    anchors.left: parent.left
    anchors.right: parent.right
    height: 1
    color: Plugin.Tokens.sep
  }

  Item {
    id: main
    anchors.top: separator.bottom
    anchors.bottom: footer.top
    anchors.left: parent.left
    anchors.right: parent.right

    Parts.EmptyState {
      anchors.fill: parent
      opacity: root.idle ? 1 : 0
      visible: opacity > 0
      Behavior on opacity { NumberAnimation { duration: 140 } }
      onPrefixChosen: prefix => {
        query.setText(prefix + " ")
        root.focusQuery()
      }
    }

    Item {
      id: results
      anchors.fill: parent
      opacity: root.idle ? 0 : 1
      visible: opacity > 0
      Behavior on opacity {
        SequentialAnimation {
          PauseAnimation { duration: root.idle ? 0 : 30 }
          NumberAnimation { duration: 140 }
        }
      }

      Item {
        id: listPane
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        width: Plugin.Tokens.listWidth

        Parts.ResultList {
          id: list
          anchors.fill: parent
          anchors.margins: Style.space(10)
          freshKeys: root.freshKeys
          rows: root.rows
          selectedIndex: root.selectedIndex
          onPicked: index => root.select(index)
          onWeakToggled: index => root.toggleWeak()
        }

        Rectangle {
          anchors.right: parent.right
          width: 1
          height: parent.height
          color: Plugin.Tokens.sep
        }
      }

      Parts.PreviewPane {
        id: pane
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.left: listPane.right
        anchors.right: parent.right
        item: root.selectedItem
        preview: root.preview
        player: player
        markers: root.markersFor(root.selectedItem)
        editorName: root.editorName
        flash: root.flash
        onPrimaryClicked: root.act("open")
        onSecondaryClicked: root.act(root.selectedItem && root.selectedItem.offline ? "copy" : "reveal")
        onPlayClicked: if (root.selectedItem) player.toggle(root.selectedItem)
      }
    }
  }

  Parts.Footer {
    id: footer
    anchors.bottom: parent.bottom
    anchors.left: parent.left
    anchors.right: parent.right

    readonly property var idleFacts: root.service && root.service.status
      ? Results.footerIdle({files: root.service.status.files || 0, roots: root.service.status.roots || 0,
        offline: [], done: root.service.status.done || 0, total: root.service.status.total || 0}) : null

    text: root.idle ? (idleFacts ? idleFacts.text : "")
      : root.noText ? ""
      : Results.footerLeft({reply: root.reply, query: root.search.query, prefix: root.parsed.prefix,
        phase: root.reply ? root.search.phase : "words"})
    offline: root.idle && root.service && root.service.status && root.service.status.offline
      ? root.service.status.offline : []
    progress: idleFacts ? idleFacts.progress : null
    indexed: !root.idle && root.service && root.service.status && typeof root.service.status.files === "number"
      ? root.service.status.files : -1
    reconcile: root.service && root.service.volumes ? Volumes.footer(root.service.volumes, root.service.clock) : null
    hints: root.idle || !root.reply
      ? (idleFacts && idleFacts.progress ? [{keys: ["Ctrl", "I"], label: "progress"}] : []).concat([{keys: ["Esc"], label: "close"}])
      : root.hintsFor(root.selectedRow)
    onProgressClicked: root.toggleProgress()
  }

  Rectangle {
    id: progressPopover
    readonly property var progress: root.service ? root.service.progress : null
    visible: root.progressOpen
    anchors.right: parent.right
    anchors.rightMargin: Style.space(18)
    anchors.bottom: footer.top
    anchors.bottomMargin: Style.space(6)
    width: Style.space(460)
    height: popoverColumn.implicitHeight + 2 * Style.space(14)
    radius: Style.cornerRadius
    color: Color.popups.background
    border.width: 1
    border.color: Plugin.Tokens.sep

    Column {
      id: popoverColumn
      x: Style.space(14)
      y: Style.space(14)
      width: parent.width - 2 * x
      spacing: Style.space(10)

      Row {
        id: popoverHead
        readonly property var head: Setup.indexHead(progressPopover.progress, null)
        spacing: Style.space(10)

        Parts.Label {
          id: popoverTitle
          text: {
            var title = Setup.indexTitle(progressPopover.progress, "")
            return title === "Indexing your files" ? "Indexing" : title
          }
          color: Color.foreground
          font.pixelSize: Style.font.body
          font.bold: true
        }

        Parts.Label {
          anchors.baseline: popoverTitle.baseline
          text: popoverHead.head.count
          color: Color.foreground
          font.pixelSize: Style.font.body
          font.bold: true
        }

        Parts.SetupFacts {
          anchors.baseline: popoverTitle.baseline
          tokens: popoverHead.head.facts
        }
      }

      Parts.KindProgress {
        width: parent.width
        progress: progressPopover.progress
        labelWidth: Style.space(64)
        textWidth: Style.space(170)
      }
    }
  }
}
