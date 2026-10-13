import QtQuick
import Quickshell
import qs.Commons
import "." as Plugin
import "ui" as Parts
import "lib/setup.js" as Setup

// The first-run flow (boards Setup, Discover, Exclusions, Indexing; motion M3). The step comes
// from daemon facts; only "Back" and the leave-out tree are local. Overlay sizes the card from
// panelWidth and panelHeight.
FocusScope {
  id: root
  objectName: "omafindSetup"

  property var service: null
  property bool back: false
  // "" or "tree" (board 11b).
  property string sub: ""
  property string treeRoot: ""

  signal closeRequested()
  signal searchRequested()

  readonly property alias folders: foldersPage
  readonly property alias tree: treeLoader
  readonly property int step: Setup.step({runtimeProgress: service ? service.runtimeProgress : null,
    progress: service ? service.progress : null, back: back})
  readonly property var size: Setup.panelSize(step, step === 2 ? sub : "")
  readonly property real panelWidth: Style.space(size.width)
  // The 4 covers the card border on both edges.
  readonly property real panelHeight: step === 2 && sub === ""
    ? Math.max(Style.space(size.height), 2 * Plugin.Tokens.setupPadding + head.height + Plugin.Tokens.setupGap
      + foldersPage.contentNeed + 4)
    : Style.space(size.height) + (step === 3 ? indexPage.extraHeight : 0)
  readonly property var discover: service ? service.discover : null
  readonly property string indexFailure: step === 3 && service ? Setup.indexFailure(service.progress, service.setupError) : ""
  readonly property string home: discover && discover.home ? discover.home : (Quickshell.env("HOME") || "")

  function reset() {
    back = false
    sub = ""
    treeRoot = ""
  }

  function focusFirst() {
    if (sub === "tree" && treeLoader.item) treeLoader.item.focusFirst()
    else if (step === 1) enginePage.focusFirst()
    else if (step === 2) foldersPage.focusFirst()
    else indexPage.focusFirst()
  }

  function ensureScan() {
    if (!service || service.scanning) return
    if (!service.discover || service.discoverError !== "") service.scan()
  }

  function showFolders() {
    back = false
    ensureScan()
  }

  function showTree(path) {
    treeRoot = path
    foldersPage.requestTree(path)
    sub = "tree"
    Qt.callLater(focusFirst)
  }

  function closeTree() {
    sub = ""
    Qt.callLater(focusFirst)
  }

  function handleKey(event) {
    var ctrl = (event.modifiers & Qt.ControlModifier) !== 0
    if (sub === "tree" && step === 2) {
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

  onStepChanged: {
    if (step !== 2) sub = ""
    if (step === 2) {
      ensureScan()
      foldersPage.prefetch()
    }
    if (step === 3) indexPage.begin()
    Qt.callLater(focusFirst)
  }

  Component.onCompleted: {
    if (step === 2) {
      ensureScan()
      foldersPage.prefetch()
    }
    if (step === 3) indexPage.begin()
  }

  Connections {
    target: root.service
    ignoreUnknownSignals: true
    function onDiscoverChanged() { if (root.step === 2) foldersPage.prefetch() }
  }

  // Out 120 ms, then in 160 ms after a 120 ms delay (M3 step swap).
  component Swap: FocusScope {
    id: swap
    property bool shown: false
    opacity: swap.shown ? 1 : 0
    visible: opacity > 0
    enabled: swap.shown
    Behavior on opacity {
      SequentialAnimation {
        PauseAnimation { duration: swap.shown ? 120 : 0 }
        NumberAnimation { duration: swap.shown ? 160 : 120; easing.type: Easing.BezierSpline; easing.bezierCurve: Plugin.Tokens.ease }
      }
    }
  }

  Item {
    id: content
    anchors.fill: parent
    anchors.margins: Plugin.Tokens.setupPadding

    Swap {
      id: head
      shown: root.sub === ""
      width: parent.width
      height: headColumn.implicitHeight

      Column {
        id: headColumn
        width: parent.width
        spacing: Plugin.Tokens.setupGap

        Parts.SetupHeader {
          width: parent.width
          title: root.step === 1 ? "Set up omafind" : root.step === 2 ? "Pick the folders to search" : "Indexing your files"
          stepText: Setup.stepLabel(root.step)
          subtitle: root.step === 1 ? "Everything runs on this machine. Nothing downloads until you press a button."
            : root.step === 3 ? root.indexFailure || "You can search already. Results fill in as files finish."
            : root.service && !root.service.scanning && root.service.discoverError !== "" ? root.service.discoverError
            : ""
          subtitleColor: root.step === 2 || root.indexFailure !== "" ? Color.urgent : Plugin.Tokens.dim
          spinning: root.step === 2 && !!root.service && root.service.scanning
          facts: root.step !== 2 ? []
            : root.service && root.service.scanning ? Setup.scanningFacts()
            : root.discover ? Setup.scanFacts(root.discover)
            : []
        }

        Parts.StepChips {
          chips: Setup.chips(root.step)
        }

        Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }
      }
    }

    Item {
      id: stage
      anchors.top: head.bottom
      anchors.topMargin: Plugin.Tokens.setupGap
      anchors.bottom: parent.bottom
      width: parent.width

      Swap {
        anchors.fill: parent
        shown: root.step === 1

        Parts.SetupEngine {
          id: enginePage
          anchors.fill: parent
          service: root.service
          onNextRequested: root.showFolders()
        }
      }

      Swap {
        anchors.fill: parent
        shown: root.step === 2 && root.sub === ""

        Parts.SetupFolders {
          id: foldersPage
          anchors.fill: parent
          service: root.service
          onBackRequested: root.back = true
          onTreeRequested: path => root.showTree(path)
        }
      }

      Swap {
        anchors.fill: parent
        shown: root.step === 3

        Parts.SetupIndex {
          id: indexPage
          anchors.fill: parent
          service: root.service
          onCloseRequested: root.closeRequested()
          onSearchRequested: root.searchRequested()
        }
      }
    }

    Swap {
      anchors.fill: parent
      shown: root.step === 2 && root.sub === "tree"

      Loader {
        id: treeLoader
        anchors.fill: parent
        active: root.sub === "tree" && root.treeRoot !== ""
        sourceComponent: Parts.SetupLeaveOut {
          service: root.service
          rootPath: root.treeRoot
          home: root.home
          rates: root.discover ? root.discover.rates : null
          device: root.discover && root.discover.device ? root.discover.device : "gpu"
          stepText: Setup.stepLabel(2)
          initialExcludes: {
            var c = foldersPage.allRows.find(row => row.path === root.treeRoot)
            return c ? foldersPage.excludesFor(c) : []
          }
          initialChosen: {
            var c = foldersPage.allRows.find(row => row.path === root.treeRoot)
            return c ? foldersPage.chosenFor(c) : []
          }
          onDone: (excludes, chosen) => {
            foldersPage.commitExcludes(root.treeRoot, excludes, chosen)
            root.closeTree()
          }
          onCancelled: root.closeTree()
        }
      }
    }
  }
}
