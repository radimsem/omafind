import QtQuick
import qs.Commons
import ".." as Plugin
import "../lib/setup.js" as Setup
import "../lib/ledger.js" as Ledger
import "../lib/tree.js" as Tree
import "../lib/volumes.js" as Volumes

// The drive dialog (boards NewDrive, MotionFresh step 4): the drive's facts, its folders from a
// discover_start with this volume, then "Index this drive" and the drive's own progress. Overlay
// sizes the card from panelWidth and panelHeight.
FocusScope {
  id: root
  objectName: "omafindDrive"

  property var service: null
  property string uuid: ""
  // Session state. Maps are replaced, never mutated, so bindings see each change.
  property var checked: ({})
  property var excludes: ({})
  property var chosenIn: ({})
  // "pick", then "run" after Index this drive, then "done".
  property string phase: "pick"
  property bool sawProgress: false
  // "" or "tree" (board 11b on a drive folder).
  property string sub: ""
  property string treeRoot: ""
  property var firstRow: null

  signal closeRequested()

  readonly property var volume: service && service.volumes.drives[uuid] ? service.volumes.drives[uuid]
    : ({uuid: uuid, label: "", fs: "", size: 0, mount: null})
  readonly property var discover: service && service.driveDiscover && service.driveDiscover.volume === uuid
    ? service.driveDiscover : null
  readonly property string mount: volume.mount || (discover && discover.scan && discover.scan.roots
    && discover.scan.roots.length ? discover.scan.roots[0] : "")
  readonly property string label: Volumes.driveLabel({uuid: uuid, label: volume.label, mount: mount})
  readonly property bool scanning: !!service && service.driveScanning
  readonly property var candidates: discover && discover.candidates ? discover.candidates : []
  readonly property var rates: discover ? discover.rates : null
  readonly property string device: discover && discover.device ? discover.device : "gpu"
  readonly property var trees: service ? service.trees : ({})
  readonly property var kept: {
    var out = {}
    for (var i = 0; i < candidates.length; i++) out[candidates[i].path] = keptFor(candidates[i])
    return out
  }
  readonly property var totals: Setup.totals(candidates.map(c => ({checked: isChecked(c), counts: kept[c.path]})), rates, device)
  readonly property bool anyChecked: candidates.some(c => isChecked(c))
  readonly property var progress: service ? service.progress : null
  readonly property var footer: Volumes.dialogFooter(progress, uuid, label)
  readonly property var datasets: discover && discover.not_proposed && Array.isArray(discover.not_proposed.datasets)
    ? discover.not_proposed.datasets : []
  readonly property string errorText: service ? service.setupError || service.driveError : ""

  readonly property real panelWidth: Style.space(1120)
  // The 4 covers the card border on both edges.
  readonly property real panelHeight: sub === "tree" ? Style.space(948)
    : body.implicitHeight + 2 * Plugin.Tokens.setupPadding + 4

  function reset() {
    checked = {}
    excludes = {}
    chosenIn = {}
    phase = "pick"
    sawProgress = false
    sub = ""
    treeRoot = ""
    closeTimer.stop()
  }

  function begin() {
    if (service && uuid) service.scanDrive(uuid)
  }

  function focusFirst() {
    if (sub === "tree" && treeLoader.item) treeLoader.item.focusFirst()
    else if (firstRow) firstRow.focusCheck()
    else if (start.enabled) start.forceActiveFocus()
    else cancel.forceActiveFocus()
  }

  function handleKey(event) {
    var ctrl = (event.modifiers & Qt.ControlModifier) !== 0
    if (sub === "tree") {
      if (event.key === Qt.Key_Escape) {
        closeTree()
        event.accepted = true
      } else if (ctrl && event.key === Qt.Key_Z && treeLoader.item) {
        treeLoader.item.undo()
        event.accepted = true
      }
      return
    }
    if (event.key === Qt.Key_Escape) {
      root.closeRequested()
      event.accepted = true
    }
  }

  function rel(path) {
    return Volumes.relPath(path, mount)
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

  // Counts after the leave-outs; the scan's own counts until a tree edit asks for the tree.
  function keptFor(c) {
    var tree = trees ? trees[c.path] : null
    if (tree && excludes[c.path] !== undefined) return Tree.ledger(tree, excludesFor(c), chosenFor(c), Ledger.compute).kept
    return c.counts || {}
  }

  function setMap(name, key, value) {
    var next = Object.assign({}, root[name])
    next[key] = value
    root[name] = next
  }

  function rowFacts(c) {
    var tokens = [{k: "dirs", v: Setup.count(c.dirs || 0), tone: "plain"}]
    var out = excludesFor(c).filter(e => e.rule !== "secrets").length
    if (out) tokens.push({k: "left out", v: Setup.count(out), tone: "plain"})
    return tokens.concat((c.exts || []).slice(0, 2).map(ext => ({k: ext[0], v: Setup.count(ext[1]), tone: "plain"})))
  }

  function seconds(value) {
    return value < 90 ? Math.round(value) + " s" : Math.round(value / 60) + " min"
  }

  function datasetFacts(list) {
    if (!list.length) return []
    var tokens = [{k: "not proposed", v: "", tone: "plain"}]
    list.forEach(d => {
      tokens.push({k: "dataset", v: rel(d.path), tone: "plain"})
      tokens.push({k: "files", v: Setup.count(d.files), tone: "plain"})
      if (d.match && d.match.length === 2) tokens.push({k: "match", v: Setup.count(d.match[0]) + "/" + Setup.count(d.match[1]), tone: "plain"})
    })
    return tokens
  }

  function showTree(path) {
    treeRoot = path
    if (service && !(trees && trees[path])) service.requestTree(path)
    sub = "tree"
    Qt.callLater(focusFirst)
  }

  function closeTree() {
    sub = ""
    Qt.callLater(focusFirst)
  }

  function commitExcludes(path, list, chosen) {
    setMap("excludes", path, list)
    setMap("chosenIn", path, chosen || [])
  }

  // Appends the chosen folders to `roots` under this volume, replacing any root at the same path.
  function startIndexing() {
    var chosen = []
    var skipped = []
    candidates.forEach(c => {
      if (!isChecked(c)) return
      chosen.push(c.path)
      chosenFor(c).forEach(folder => chosen.push(c.path + "/" + folder))
      excludesFor(c).forEach(e => {
        if (e.rule !== "secrets") skipped.push(e.path === "" ? c.path : c.path + "/" + e.path)
      })
    })
    var fresh = Tree.toRoots(chosen, skipped, () => root.uuid)
    var paths = fresh.map(r => r.path)
    var roots = service.settings.roots.filter(r => paths.indexOf(r.path) < 0).concat(fresh)
    if (!service.startIndexing(roots, null, uuid)) return
    sawProgress = false
    phase = "run"
  }

  // sawProgress is set only while indexing, so a finished run from before the click does not count.
  readonly property bool finished: {
    var volumes = progress && progress.volumes ? progress.volumes : null
    var mine = volumes ? volumes[uuid] : null
    return sawProgress && !!mine && mine.done >= mine.total && (mine.total > 0 || !progress.running)
  }

  onFinishedChanged: {
    if (!finished || phase !== "run") return
    phase = "done"
    closeTimer.restart()
  }
  onUuidChanged: {
    reset()
    begin()
  }
  Component.onCompleted: begin()

  Connections {
    target: root.service
    ignoreUnknownSignals: true
    function onProgressChanged() { if (root.phase === "run") root.sawProgress = true }
  }

  // Board decision: the dialog closes 1 s after "Indexed <label>".
  Timer {
    id: closeTimer
    interval: 1000
    onTriggered: root.closeRequested()
  }

  Item {
    anchors.fill: parent
    anchors.margins: Plugin.Tokens.setupPadding
    opacity: root.sub === "" ? 1 : 0
    visible: opacity > 0
    enabled: root.sub === ""
    Behavior on opacity { NumberAnimation { duration: 120 } }

    Column {
      id: body
      width: parent.width
      spacing: Plugin.Tokens.setupGap

      // `.p-head`: title over the drive facts, the "removable" tag at the top right.
      Item {
        width: parent.width
        height: head.implicitHeight + Style.space(6)

        Column {
          id: head
          y: Style.space(2)
          width: parent.width - tag.width - Style.space(12)
          spacing: Style.space(4)

          Text {
            text: root.label
            textFormat: Text.PlainText
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.heading
            font.bold: true
          }

          SetupFacts {
            width: Math.min(implicitWidth, parent.width)
            fontSize: Style.font.bodySmall
            tokens: Volumes.driveFacts({mount: root.mount, fs: root.volume.fs},
              root.scanning ? {running: true} : root.discover && root.discover.scan ? {seconds: root.discover.scan.seconds} : null)
          }
        }

        Rectangle {
          id: tag
          anchors.right: parent.right
          y: Style.space(2)
          width: tagText.implicitWidth + 2 * Style.space(6)
          height: Style.space(18)
          radius: Style.cornerRadius
          color: Style.hoverFill

          Text {
            id: tagText
            anchors.centerIn: parent
            text: "removable"
            textFormat: Text.PlainText
            color: Plugin.Tokens.fg2
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            font.bold: true
          }
        }
      }

      Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }

      Column {
        width: parent.width

        FolderTable {
          id: header
          width: parent.width
          folderLabel: "Folder on the drive"
        }

        Repeater {
          model: root.candidates
          onItemAdded: (index, item) => { if (index === 0) root.firstRow = item }

          delegate: FolderRow {
            required property var modelData
            required property int index
            readonly property var c: modelData
            readonly property var counts: root.kept[c.path] || {}
            readonly property var estimate: Setup.estimate(counts, root.rates, root.device)
            objectName: "omafindDriveRow"
            width: header.width
            table: header
            path: c.path
            check: root.isChecked(c) ? "on" : "off"
            checkLabel: "Include " + root.rel(c.path).replace(/^\//, "")
            name: root.rel(c.path)
            facts: root.rowFacts(c)
            cells: Setup.KINDS.map(k => ({n: counts[k] || 0, cut: false}))
            indexText: root.rates ? Setup.mb(estimate.bytes) : ""
            timeText: root.rates ? root.seconds(estimate.seconds) : ""
            action: "filter"
            actionLabel: "Add an exclude to " + root.rel(c.path).replace(/^\//, "")
            fill: root.isChecked(c) ? "on" : ""
            enabled: root.phase === "pick"
            onToggled: root.setMap("checked", c.path, !root.isChecked(c))
            onActionClicked: root.showTree(c.path)
          }
        }

        Item {
          visible: root.datasets.length > 0
          width: parent.width
          height: visible ? Style.space(12) + datasetRow.implicitHeight : 0

          SetupFacts {
            id: datasetRow
            x: Plugin.Tokens.tablePadding
            y: Style.space(12)
            width: Math.min(implicitWidth, parent.width - 2 * x)
            tokens: root.datasetFacts(root.datasets)
          }
        }
      }

      Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }

      SetupFacts {
        fontSize: Style.font.bodySmall
        tokens: [{k: "watch", v: "off · removable", tone: "plain"}, {k: "reconcile", v: "on mount", tone: "plain"}]
      }

      Text {
        visible: root.errorText !== ""
        width: parent.width
        wrapMode: Text.Wrap
        text: root.errorText
        textFormat: Text.PlainText
        color: Color.urgent
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }

      // `.fx-bot`: the totals and buttons cross-fade to the drive's progress over 180 ms.
      Item {
        width: parent.width
        height: Style.space(32)

        Item {
          anchors.fill: parent
          opacity: root.phase === "pick" ? 1 : 0
          visible: opacity > 0
          enabled: root.phase === "pick"
          Behavior on opacity { NumberAnimation { duration: 180 } }

          SetupFacts {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(implicitWidth, parent.width - buttons.width - Style.space(8))
            fontSize: Style.font.body
            gap: Style.space(18)
            tokens: [{k: "selected", v: "<b>" + Setup.count(root.totals.files) + "</b> files", tone: "plain"},
              {k: "index", v: "<b>" + Setup.mb(root.totals.bytes) + "</b>", tone: "plain"},
              {k: "time", v: "<b>" + root.seconds(root.totals.seconds) + "</b>", tone: "plain"}]
          }

          Row {
            id: buttons
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(8)

            ActionButton {
              id: cancel
              objectName: "omafindDriveCancel"
              text: "Cancel"
              focusable: true
              onClicked: root.closeRequested()
            }

            ActionButton {
              id: start
              objectName: "omafindDriveIndex"
              text: "Index this drive"
              primary: true
              neutral: true
              focusable: true
              enabled: !!root.discover && !root.scanning && root.anyChecked && !!root.service && !root.service.indexPending
              onClicked: root.startIndexing()
            }
          }
        }

        Row {
          anchors.fill: parent
          opacity: root.phase === "pick" ? 0 : 1
          visible: opacity > 0
          spacing: Style.space(8)
          Behavior on opacity { NumberAnimation { duration: 180 } }

          Text {
            id: indexLabel
            anchors.verticalCenter: parent.verticalCenter
            text: root.footer.text
            textFormat: Text.PlainText
            color: root.phase === "done" ? Plugin.Palette.green : Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            Behavior on color { ColorAnimation { duration: 200 } }
          }

          ProgressBar {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - indexLabel.width - indexCount.width - 2 * parent.spacing
            fraction: root.footer.fraction
            done: root.phase === "done"
          }

          Text {
            id: indexCount
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(implicitWidth, Style.space(120))
            horizontalAlignment: Text.AlignRight
            text: root.footer.count
            textFormat: Text.PlainText
            color: root.phase === "done" ? Plugin.Palette.green : Plugin.Tokens.fg2
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            Behavior on color { ColorAnimation { duration: 200 } }
          }
        }
      }
    }
  }

  Loader {
    id: treeLoader
    anchors.fill: parent
    anchors.margins: Plugin.Tokens.setupPadding
    active: root.sub === "tree" && root.treeRoot !== ""
    sourceComponent: SetupLeaveOut {
      service: root.service
      rootPath: root.treeRoot
      home: ""
      rates: root.rates
      device: root.device
      initialExcludes: {
        var c = root.candidates.find(row => row.path === root.treeRoot)
        return c ? root.excludesFor(c) : []
      }
      initialChosen: {
        var c = root.candidates.find(row => row.path === root.treeRoot)
        return c ? root.chosenFor(c) : []
      }
      onDone: (excludes, chosen) => {
        root.commitExcludes(root.treeRoot, excludes, chosen)
        root.closeTree()
      }
      onCancelled: root.closeTree()
    }
  }
}
