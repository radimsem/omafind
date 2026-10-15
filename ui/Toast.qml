import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import qs.Commons
import ".." as Plugin

// `.ntf` at the top right. Its own window, so it stays after the overlay closes.
PanelWindow {
  id: root

  property string title: ""
  property var tokens: []
  property bool error: false
  property bool showing: false

  function show(nextTitle, nextTokens, isError) {
    title = nextTitle
    tokens = nextTokens || []
    error = isError === true
    if (!visible) screen = focusedScreen()
    showing = true
    visible = true
    hold.restart()
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
  // Clicks pass through to the windows below.
  mask: Region {}

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
        visible: root.tokens.length > 0
        width: Math.min(implicitWidth, column.width)
        tokens: root.tokens
        fontSize: Style.font.bodySmall
      }
    }
  }
}
