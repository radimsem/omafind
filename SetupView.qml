import QtQuick
import Quickshell
import qs.Commons
import "." as Plugin
import "ui" as Parts
import "lib/setup.js" as Setup

// The first-run flow derives its step from daemon facts; only "Back" is local.
FocusScope {
  id: root
  objectName: "omafindSetup"

  property var service: null
  property bool back: false

  signal closeRequested()
  signal searchRequested()

  readonly property alias folders: foldersPage
  readonly property int step: Setup.step({runtimeProgress: service ? service.runtimeProgress : null,
    progress: service ? service.progress : null, back: back})
  readonly property var size: Setup.panelSize(step)
  readonly property real panelWidth: Style.space(size.width)
  readonly property real panelHeight: Style.space(size.height) + (step === 3 ? indexPage.extraHeight : 0)
    + (step === 1 ? enginePage.extraHeight : 0)
  readonly property string walkError: service ? Setup.walkError(service.walks) : ""
  readonly property var discover: service ? service.discover : null
  readonly property string indexFailure: step === 3 && service ? Setup.indexFailure(service.progress,
    service.indexError ? (service.indexError.title + " " + service.indexError.detail).trim() : "") : ""
  readonly property string home: discover && discover.home ? discover.home : (Quickshell.env("HOME") || "")


  function reset() {
    back = false
    if (step === 2) ensureScan(true)
    if (step === 3 && service) service.getBinds()
  }

  function stop() {
    indexPage.stop()
  }

  function focusFirst() {
    if (step === 1) enginePage.focusFirst()
    else if (step === 2) foldersPage.focusFirst()
    else indexPage.focusFirst()
  }

  function handleKey(event) {
    if (event.key === Qt.Key_Escape) {
      root.closeRequested()
      event.accepted = true
    }
  }

  onStepChanged: {
    if (step === 2) ensureScan()
    if (step === 3) indexPage.begin()
    Qt.callLater(focusFirst)
  }

  Component.onCompleted: {
    if (step === 2) ensureScan()
    if (step === 3) indexPage.begin()
  }

  function ensureScan(force) {
    if (!service || service.scanning) return
    if (force || !service.discover || !!service.folderError || walkError !== "") service.scan()
  }

  function showFolders() {
    back = false
    ensureScan()
  }


  Connections {
    target: root.service
    function onReadyChanged() {
      if (root.visible && root.step === 2 && root.service.ready) root.ensureScan(true)
    }
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
      shown: true
      width: parent.width
      height: headColumn.implicitHeight

      Column {
        id: headColumn
        width: parent.width
        spacing: Plugin.Tokens.setupGap

        Parts.SetupHeader {
          width: parent.width
          title: root.step === 1 ? "Set up omafind" : root.step === 2 ? "Pick the folders to search"
            : Setup.indexTitle(root.service ? root.service.progress : null, root.indexFailure)
          stepText: Setup.stepLabel(root.step)
          subtitle: root.step === 1 ? "Everything runs on this machine. Nothing downloads until you press a button."
            : root.step === 3 ? root.indexFailure || "You can search already. Results fill in as files finish."
            : root.service && !root.service.scanning && root.service.folderError
              ? (root.service.folderError.title + " " + root.service.folderError.detail).trim()
            : root.walkError !== "" ? Setup.folderError(root.walkError)
            : ""
          subtitleColor: root.step === 2 || root.indexFailure !== "" ? Color.urgent : Plugin.Tokens.dim
          spinning: root.step === 2 && !!root.service && (root.service.scanning
            || Object.keys(root.service.walks).some(key => !root.service.walks[key].done))
          facts: root.step !== 2 || !root.discover ? []
            : Setup.scanFacts(foldersPage.folders.length, root.service.walks)
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
        shown: root.step === 2

        Parts.SetupFolders {
          id: foldersPage
          anchors.fill: parent
          service: root.service
          onBackRequested: root.back = true
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

  }
}
