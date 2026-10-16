import QtQuick
import qs.Commons
import ".." as Plugin
import "../lib/setup.js" as Setup
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
  property var choices: Tree.initial([])
  property bool seeded: false
  property var proposed: []
  // "pick", then "run" after Index this drive, then "done".
  property string phase: "pick"
  property bool sawProgress: false

  signal closeRequested()

  readonly property var volume: service && service.volumes.drives[uuid] ? service.volumes.drives[uuid]
    : ({uuid: uuid, label: "", fs: "", size: 0, mount: null})
  readonly property var discover: service && service.driveDiscover && service.driveDiscover.volume === uuid
    ? service.driveDiscover : null
  readonly property string mount: volume.mount || (discover && discover.roots && discover.roots.length
    ? discover.roots[0].path : "")
  readonly property string label: Volumes.driveLabel({uuid: uuid, label: volume.label, mount: mount})
  readonly property bool scanning: !!service && service.driveScanning
  readonly property var folders: discover && Array.isArray(discover.folders) ? discover.folders : []
  readonly property var walk: service && mount && service.walks[mount] ? service.walks[mount] : null
  readonly property var rates: discover ? discover.rates : null
  readonly property string device: discover && discover.device ? discover.device : "gpu"
  readonly property bool anyChecked: choices.chosen.length > 0
  readonly property var progress: service ? service.progress : null
  readonly property var footer: Volumes.dialogFooter(progress, uuid, label)
  readonly property var failure: driveFailure()

  readonly property real panelWidth: Style.space(1120)
  // The 4 covers the card border on both edges.
  readonly property real panelHeight: body.implicitHeight + 2 * Plugin.Tokens.setupPadding + 4

  function reset() {
    choices = Tree.initial([])
    seeded = false
    proposed = []
    phase = "pick"
    sawProgress = false
    closeTimer.stop()
  }

  function begin() {
    if (service && uuid) service.scanDrive(uuid)
  }

  // The dialog's one error: its own request's, the drive walk's, then the drive's index run.
  function driveFailure() {
    if (!service) return null
    return service.driveError || (walk && walk.failure ? walk.failure : null)
      || (phase === "run" ? service.indexError : null)
  }

  function retry() {
    if (phase === "run") startIndexing()
    else begin()
  }

  function focusFirst() {
    if (tree.focusFirst()) return
    if (start.enabled) start.forceActiveFocus()
    else cancel.forceActiveFocus()
  }

  function handleKey(event) {
    if (event.key === Qt.Key_Escape) {
      root.closeRequested()
      event.accepted = true
    }
  }

  // Every folder on the drive starts checked.
  function seed() {
    if (seeded || !folders.length) return
    choices = {chosen: folders.map(folder => folder.path), skipped: []}
    seeded = true
    offerDatasets()
  }

  function offerDatasets() {
    if (!service || !seeded) return
    var found = Object.assign({}, service.datasets, service.worktrees)
    var list = Object.keys(found).map(path => found[path])
    choices = Tree.addDatasets(choices, list, proposed)
    proposed = proposed.concat(list.map(entry => entry.path).filter(path => proposed.indexOf(path) < 0))
  }

  function seconds(value) {
    return value < 90 ? Math.round(value) + " s" : Math.round(value / 60) + " min"
  }

  // Appends the chosen folders to `roots` under this volume, replacing any root at the same path.
  function startIndexing() {
    var fresh = Tree.toRoots(choices.chosen, choices.skipped, () => root.uuid)
    var paths = fresh.map(r => r.path)
    var roots = service.settings.roots.filter(r => paths.indexOf(r.path) < 0).concat(fresh)
    if (!service.startIndexing(roots, uuid)) return
    sawProgress = false
    phase = "run"
  }

  onFoldersChanged: seed()

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
    function onDatasetsChanged() { root.offerDatasets() }
    function onWorktreesChanged() { root.offerDatasets() }
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

          Label {
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
              root.scanning || (root.walk && !root.walk.done) ? {running: true}
              : root.walk ? {seconds: root.walk.seconds || 0} : null)
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

          Label {
            id: tagText
            anchors.centerIn: parent
            text: "removable"
            textFormat: Text.PlainText
            color: Plugin.Tokens.fg2
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
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

        FolderTree {
          id: tree
          width: parent.width
          height: Math.max(1, Math.min(tree.count, 10)) * Plugin.Tokens.tableRow
          service: root.service
          table: header
          folders: root.folders
          choices: root.choices
          mount: root.mount
          rates: root.rates
          device: root.device
          locked: root.phase !== "pick"
          onChoicesEdited: next => root.choices = next
        }
      }

      Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }

      SetupFacts {
        fontSize: Style.font.bodySmall
        tokens: [{k: "watch", v: "off · removable", tone: "plain"}, {k: "reconcile", v: "on mount", tone: "plain"}]
      }

      ErrorCard {
        objectName: "omafindDriveError"
        width: parent.width
        error: root.failure
        visible: !!error
        retryHere: true
        onRetry: root.retry()
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
            tokens: [{k: "selected", v: "<b>" + Setup.count(tree.totals.files) + "</b> files", tone: "plain"},
              {k: "index", v: "<b>" + Setup.mb(tree.totals.bytes) + "</b>", tone: "plain"},
              {k: "time", v: "<b>" + root.seconds(tree.totals.seconds) + "</b>", tone: "plain"}]
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

          Label {
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

          Label {
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

}
