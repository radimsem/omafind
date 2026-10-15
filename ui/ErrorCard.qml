import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import ".." as Plugin
import "../lib/errors.js" as Errors

// One failure in the anatomy of `.ban`: a glyph, the bold title, the detail and the fix buttons on
// the right. `error` is an error object (docs/ipc.md "Errors"); the card hides while it is null.
Rectangle {
  id: root

  property var error: null
  // Views with a primary control of their own (the setup footer) leave the card's Retry off.
  property bool retryHere: false
  property string retryText: "Retry"
  // Toasts and the preview pane: no pacman line and at most two lines of detail.
  property bool compact: false
  property bool focusable: false
  property string tone: Errors.tone(error ? error.code : "")
  // Fact tokens after the title (the disk banner).
  property var tokens: []
  property bool installing: false
  property int waited: 0

  // The Retry button was pressed, or the packages of an install fix are now present.
  signal retry()

  readonly property int pollInterval: 2000
  readonly property int pollLimit: 600000
  readonly property color toneColor: tone === "warn" ? Plugin.Palette.yellow : Color.urgent
  readonly property var packages: Errors.hasInstall(error) ? error.fix.packages : []
  // A new object with the same code (progress resends tool_errors) keeps the install running.
  readonly property string fixKey: error ? String(error.code) : ""
  readonly property string command: compact || !error ? "" : Errors.installCommand(error.fix)
  readonly property string log: error && error.log ? String(error.log) : ""

  function install() {
    Quickshell.execDetached(["omarchy-launch-floating-terminal-with-presentation", "omarchy-pkg-add"].concat(packages))
    waited = 0
    installing = true
  }

  // Views call this when their own Retry runs, so the poll never retries a second time.
  function stopInstalling() {
    installing = false
    waited = 0
  }

  visible: !!error
  implicitHeight: Math.max(Style.space(44), Math.max(body.implicitHeight, actions.implicitHeight) + 2 * Style.space(9))
  color: Util.alpha(toneColor, 0.08)

  onFixKeyChanged: stopInstalling()
  Component.onDestruction: stopInstalling()

  Timer {
    interval: root.pollInterval
    repeat: true
    running: root.installing
    onTriggered: {
      root.waited += interval
      if (root.waited >= root.pollLimit) root.stopInstalling()
      else if (!present.running) present.running = true
    }
  }

  // Exits 0 once every package is installed.
  Process {
    id: present
    command: ["omarchy-pkg-present"].concat(root.packages)
    onExited: (exitCode, exitStatus) => {
      if (!root.installing || exitCode !== 0 || exitStatus !== 0) return
      root.stopInstalling()
      root.retry()
    }
  }

  FontMetrics {
    id: lineMetrics
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }

  Item {
    id: glyph
    anchors.left: parent.left
    anchors.leftMargin: Style.space(16)
    y: body.y
    width: Style.space(14)
    height: lineMetrics.height

    Icon {
      anchors.centerIn: parent
      name: "warn"
      color: root.toneColor
    }
  }

  Column {
    id: body
    anchors.left: glyph.right
    anchors.leftMargin: Style.space(10)
    anchors.right: actions.left
    anchors.rightMargin: actions.width > 0 ? Style.space(10) : 0
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(4)

    Flow {
      width: parent.width
      spacing: Style.space(10)
      visible: titleLabel.text !== "" || root.tokens.length > 0

      Label {
        id: titleLabel
        width: Math.min(implicitWidth, parent.width)
        visible: text !== ""
        text: root.error && root.error.title ? root.error.title : ""
        wrapMode: Text.Wrap
        maximumLineCount: 2
        elide: Text.ElideRight
        color: Color.foreground
        font.pixelSize: Style.font.body
        font.bold: true
      }

      Facts {
        visible: root.tokens.length > 0
        tokens: root.tokens
        fontSize: Style.font.body
      }
    }

    Label {
      width: parent.width
      visible: text !== ""
      text: root.error && root.error.detail ? root.error.detail : ""
      wrapMode: Text.Wrap
      maximumLineCount: root.compact ? 2 : 3
      elide: Text.ElideRight
      font.pixelSize: Style.font.body
    }

    Row {
      visible: root.command !== ""
      spacing: Style.space(8)

      Label {
        anchors.verticalCenter: parent.verticalCenter
        width: Math.min(implicitWidth, body.width - copy.width - parent.spacing)
        elide: Text.ElideRight
        text: root.command
        color: Plugin.Tokens.dim
      }

      ActionButton {
        id: copy
        objectName: root.objectName ? root.objectName + "Copy" : ""
        buttonHeight: Style.space(22)
        fontSize: Style.font.bodySmall
        focusable: root.focusable
        text: "Copy"
        onClicked: Quickshell.execDetached(["wl-copy", root.command])
      }
    }
  }

  Row {
    id: actions
    anchors.right: parent.right
    anchors.rightMargin: Style.space(16)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(8)

    Row {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.installing
      spacing: Style.space(8)

      Spinner {
        anchors.verticalCenter: parent.verticalCenter
        running: root.installing
      }

      Label {
        anchors.verticalCenter: parent.verticalCenter
        text: "Installing in the terminal"
        font.pixelSize: Style.font.body
      }
    }

    ActionButton {
      objectName: root.objectName ? root.objectName + "Install" : ""
      anchors.verticalCenter: parent.verticalCenter
      // Stays pressable while installing: a closed terminal can be opened again.
      visible: root.packages.length > 0
      primary: true
      focusable: root.focusable
      buttonHeight: Style.space(26)
      text: "Install packages"
      onClicked: root.install()
    }

    ActionButton {
      objectName: root.objectName ? root.objectName + "Log" : ""
      anchors.verticalCenter: parent.verticalCenter
      visible: root.log !== ""
      focusable: root.focusable
      buttonHeight: Style.space(26)
      text: "Open log"
      onClicked: Quickshell.execDetached(["omarchy-launch-editor", root.log])
    }

    ActionButton {
      objectName: root.objectName ? root.objectName + "Retry" : ""
      anchors.verticalCenter: parent.verticalCenter
      // An install fix also says "then press Retry", so it gets the button too.
      visible: root.retryHere && root.retryText !== ""
        && (Errors.hasRetry(root.error) || Errors.hasInstall(root.error))
      focusable: root.focusable
      buttonHeight: Style.space(26)
      text: root.retryText
      onClicked: {
        root.stopInstalling()
        root.retry()
      }
    }
  }
}
