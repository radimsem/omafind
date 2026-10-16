import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import qs.Commons
import "." as Plugin

// `.ntf` at the top right. Its own window, so it stays after the overlay closes.
PanelWindow {
  id: root

  property string title: ""
  property var tokens: []
  property bool error: false
  property bool showing: false
  // An error object from the daemon, shown as a compact card.
  property var failure: null
  // A toast whose error has a fix stays until it is dismissed or retried.
  readonly property bool sticky: !!failure && !!failure.fix

  signal retryRequested()

  function show(nextTitle, nextTokens, isError) {
    failure = null
    title = nextTitle
    tokens = nextTokens || []
    error = isError === true
    if (!visible) screen = focusedScreen()
    showing = true
    visible = true
    hold.restart()
  }

  function showError(next) {
    if (!next) return
    failure = next
    title = next.title
    tokens = []
    error = true
    if (!visible) screen = focusedScreen()
    showing = true
    visible = true
    if (sticky) hold.stop()
    else hold.restart()
  }

  function dismiss() {
    hold.stop()
    showing = false
  }

  function focusedScreen() {
    var name = Hyprland.focusedMonitor ? String(Hyprland.focusedMonitor.name) : ""
    var screens = Quickshell.screens
    for (var i = 0; i < screens.length; i++)
      if (screens[i].name === name) return screens[i]
    return screens.length ? screens[0] : null
  }

  visible: false
  color: "transparent"
  anchors.top: true
  anchors.right: true
  margins.top: Style.space(10)
  margins.right: Style.space(10)
  implicitWidth: Style.space(380) + Style.space(12)
  implicitHeight: card.implicitHeight + Style.space(12)
  WlrLayershell.namespace: "omafind-toast"
  WlrLayershell.layer: WlrLayer.Overlay
  WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
  // Clicks pass through to the windows below, except on a toast that waits for its fix.
  mask: Region { item: root.sticky ? card : null }

  Timer {
    id: hold
    interval: 2800
    onTriggered: root.showing = false
  }

  Timer {
    id: unmap
    interval: 200
    running: !root.showing && root.visible
    onTriggered: root.visible = false
  }

  Rectangle {
    id: card
    x: Style.space(12)
    width: Style.space(380)
    implicitHeight: column.implicitHeight + 2 * Style.space(12) + 4
    radius: Style.cornerRadius
    color: Color.notifications.background
    border.width: 2
    border.color: Color.accent
    opacity: root.showing ? 1 : 0
    transform: Translate {
      x: root.showing ? 0 : Style.space(12)
      y: root.showing ? 0 : -Style.space(12)
      Behavior on x { NumberAnimation { duration: 180; easing.type: Easing.BezierSpline; easing.bezierCurve: Plugin.Tokens.ease } }
      Behavior on y { NumberAnimation { duration: 180; easing.type: Easing.BezierSpline; easing.bezierCurve: Plugin.Tokens.ease } }
    }
    Behavior on opacity { NumberAnimation { duration: 180 } }
    Accessible.role: Accessible.AlertMessage
    Accessible.name: root.title

    Column {
      id: column
      x: Style.space(14) + 2
      y: Style.space(12) + 2
      width: parent.width - 2 * (Style.space(14) + 2)
      spacing: Style.space(10)

      Row {
        visible: !root.failure
        spacing: Style.space(8)

        Icon {
          anchors.verticalCenter: parent.verticalCenter
          name: root.error ? "warn" : "search"
          size: Style.space(14)
          color: root.error ? Color.urgent : Color.accent
        }

        Label {
          anchors.verticalCenter: parent.verticalCenter
          width: Math.min(implicitWidth, column.width - Style.space(22))
          elide: Text.ElideMiddle
          text: root.title
          textFormat: Text.PlainText
          color: Color.notifications.text
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          font.bold: true
        }
      }

      Facts {
        visible: !root.failure && root.tokens.length > 0
        width: Math.min(implicitWidth, column.width)
        tokens: root.tokens
        fontSize: Style.font.bodySmall
      }

      ErrorCard {
        objectName: "omafindToastError"
        width: column.width
        compact: true
        retryHere: true
        error: root.failure
        visible: !!error
        onRetry: root.retryRequested()
      }

      ActionButton {
        objectName: "omafindToastDismiss"
        visible: root.sticky
        anchors.right: parent.right
        buttonHeight: Style.space(26)
        text: "Dismiss"
        onClicked: root.dismiss()
      }
    }
  }
}
