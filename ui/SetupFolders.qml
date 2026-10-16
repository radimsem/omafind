import QtQuick
import Quickshell
import qs.Commons
import "." as Plugin
import "../lib/setup.js" as Setup
import "../lib/tree.js" as Tree

FocusScope {
  id: root

  property var service: null
  property var choices: Tree.initial([])
  // Folders added through "Add folder" that sit outside every listed row.
  property var added: []
  // Datasets already offered, so a later walk does not skip one the user checked.
  property var proposed: []
  property bool seeded: false
  // Seeded from a finished setup: the saved choices already decided every worktree and dataset
  // the user saw, so nothing is skipped on its own.
  property bool fromSaved: false
  property bool picking: false

  signal backRequested()

  readonly property var discover: service ? service.discovery.discover : null
  readonly property string home: discover && discover.home ? discover.home : (Quickshell.env("HOME") || "")
  readonly property var rates: discover ? discover.rates : null
  // Step 2 shows its own error, else a failed start of the first index.
  readonly property var failure: service ? service.folderError || service.indexError : null
  readonly property string device: discover && discover.device ? discover.device : "gpu"
  readonly property var folders: (discover && Array.isArray(discover.folders) ? discover.folders : []).concat(added)
  // Drives mounted inside another root, such as a disk under $HOME.
  readonly property var mounts: (discover && Array.isArray(discover.roots) ? discover.roots : [])
    .map(row => row.path).filter((path, index, all) => all.some(other => other !== path && Tree.isInside(path, other)))
  readonly property var roots: Tree.toRoots(choices.chosen, choices.skipped, volumeOf, mounts)
  // Change triggers for offerDatasets, which reads both through service.discovery.
  readonly property var datasets: service ? service.discovery.datasets : ({})
  readonly property var worktrees: service ? service.discovery.worktrees : ({})
  readonly property bool ready: !!discover && !!service && !service.discovery.scanning
    && roots.length > 0 && roots.every(r => r.volume !== "" && walkDone(r.path))

  function focusFirst() {
    if (!tree.focusFirst()) {
      if (start.enabled) start.forceActiveFocus()
      else back.forceActiveFocus()
    }
  }

  function seed() {
    if (seeded || !discover || !Array.isArray(discover.folders)) return
    var saved = service ? service.settings : null
    fromSaved = !!saved && saved.setupDone && saved.roots.length > 0
    choices = fromSaved ? Tree.fromSettings(saved.roots) : Tree.initial(discover.folders)
    seeded = true
    offerDatasets()
  }

  function offerDatasets() {
    if (!service || !seeded) return
    var found = Object.assign({}, service.discovery.datasets, service.discovery.worktrees)
    var list = Object.keys(found).filter(path => {
      if (proposed.indexOf(path) >= 0) return false
      var owner = Tree.owner(path, choices)
      return owner.on || owner.path === path
    }).map(path => found[path])
    if (!list.length) return
    if (fromSaved) {
      proposed = proposed.concat(list.map(entry => entry.path))
      return
    }
    var next = Tree.addDatasets(choices, list, proposed)
    proposed = proposed.concat(list.map(entry => entry.path))
    choices = next
  }

  function walkDone(path) {
    var boundary = ""
    ;(discover && discover.roots || []).forEach(root => {
      if (Tree.isInside(path, root.path) && root.path.length > boundary.length) boundary = root.path
    })
    var found = false
    var walks = service ? service.discovery.walks : {}
    for (var folder in walks) {
      if (!Tree.isInside(path, folder) || !Tree.isInside(folder, boundary)) continue
      if (!walks[folder].done) return false
      found = true
    }
    return found
  }

  function volumeOf(path) {
    var best = null
    var rows = folders.concat(discover && Array.isArray(discover.roots) ? discover.roots : [])
    rows.forEach(row => {
      var cached = service ? service.discovery.childFolders[row.path] : null
      var volume = row.volume || (cached ? cached.volume : "")
      if (volume && Tree.isInside(path, row.path) && (!best || row.path.length > best.path.length))
        best = {path: row.path, volume: volume}
    })
    return best ? best.volume : ""
  }

  function addFolder(path) {
    picking = false
    var absolute = path === "~" ? home : path.indexOf("~/") === 0 ? home + path.slice(1) : path
    if (!folders.some(row => Tree.isInside(absolute, row.path))) {
      added = added.concat([{path: absolute, name: absolute, xdg: false, repo: false, hasChildren: true, volume: ""}])
    }
    if (!Tree.searched(absolute, choices))
      choices = Tree.click(choices, absolute, service ? Object.keys(Object.assign({}, service.discovery.datasets, service.discovery.worktrees)) : [])
    // The volume lookup must finish before the root can be saved.
    if (service) service.requestChildren(absolute)
  }

  function retry() {
    if (!service) return
    if (service.folderError) service.scan()
    else startIndexing()
  }

  function startIndexing() {
    if (!ready) return
    service.startIndexing(roots)
  }

  onDiscoverChanged: seed()
  onDatasetsChanged: offerDatasets()
  onWorktreesChanged: offerDatasets()
  onChoicesChanged: offerDatasets()
  Component.onCompleted: seed()

  FolderTable {
    id: header
    width: parent.width
  }

  FolderTree {
    id: tree
    anchors.top: header.bottom
    anchors.bottom: addRow.top
    width: parent.width
    service: root.service
    table: header
    folders: root.folders
    mounts: root.mounts
    choices: root.choices
    home: root.home
    rates: root.rates
    device: root.device
    onChoicesEdited: next => root.choices = next
  }

  Item {
    id: addRow
    anchors.bottom: footer.top
    anchors.bottomMargin: Plugin.Tokens.setupGap
    width: parent.width
    height: Style.space(12) + Math.max(addFolder.height, picker.visible ? picker.implicitHeight : 0)

    ActionButton {
      id: addFolder
      visible: !root.picking
      objectName: "omafindAddFolder"
      x: Plugin.Tokens.tablePadding
      y: Style.space(12)
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

  Column {
    id: footer
    anchors.bottom: parent.bottom
    width: parent.width
    spacing: Plugin.Tokens.setupGap

    Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }

    ErrorCard {
      objectName: "omafindFolderError"
      width: parent.width
      error: root.failure
      visible: !!error
      retryHere: true
      onRetry: root.retry()
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
        // The board bolds the count of `selected`, not the word "files".
        tokens: root.discover ? Setup.totalFacts(tree.totals, root.device).map(t => t.k === "selected"
          ? {k: t.k, v: String(t.v).replace(/^([\d,]+)/, "<b>$1</b>"), tone: "plain"} : t) : []
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
          enabled: root.ready && !root.service.indexPending
          onClicked: root.startIndexing()
        }
      }
    }
  }
}
