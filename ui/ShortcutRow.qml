import QtQuick
import qs.Commons
import ".." as Plugin

// Ported from omaone/ui/ShortcutRow.qml.
Item {
  id: root
  objectName: "omafindShortcutRow"

  property var parts: []
  property string prompt: "Press a shortcut"
  property bool recording: false
  property bool canChange: true
  property string note: ""
  // "warn" draws the note in yellow, anything else dim.
  property string noteTone: ""

  signal change()
  signal cancel()
  signal captured(int key, int modifiers)

  function take() {
    button.forceActiveFocus()
  }

  function press() {
    if (recording) cancel()
    else if (canChange) change()
  }

  implicitHeight: Style.space(28)

  Rectangle {
    id: keys
    anchors.verticalCenter: parent.verticalCenter
    width: root.recording ? promptLabel.implicitWidth + 2 * Style.space(10) : caps.implicitWidth
    height: Style.space(28)
    radius: Style.cornerRadius
    color: "transparent"
    border.width: root.recording ? 1 : 0
    border.color: Color.accent

    Row {
      id: caps
      visible: !root.recording
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(4)

      Repeater {
        model: root.parts
        delegate: SetupKey {
          required property string modelData
          text: modelData
          implicitHeight: Style.space(26)
          fontSize: Style.font.body
          padding: Style.space(8)
        }
      }
    }

    Label {
      id: promptLabel
      visible: root.recording
      anchors.centerIn: parent
      text: root.prompt
      color: Util.alpha(Color.foreground, 0.85)
      font.bold: true
    }
  }

  Label {
    anchors.left: keys.right
    anchors.leftMargin: Style.space(12)
    anchors.right: button.left
    anchors.rightMargin: Style.space(12)
    anchors.verticalCenter: parent.verticalCenter
    elide: Text.ElideRight
    text: root.note
    color: root.noteTone === "warn" ? Plugin.Palette.yellow : Plugin.Tokens.dim
  }

  // Not ActionButton: that one takes Space and Enter as presses, and a recording needs them as keys.
  Rectangle {
    id: button
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    enabled: root.recording || root.canChange
    opacity: enabled ? 1 : 0.45
    width: Math.max(Style.space(76), label.implicitWidth + 2 * Style.space(16))
    height: Style.space(28)
    radius: Style.cornerRadius
    color: mouse.containsMouse ? Style.hoverFill : "transparent"
    border.width: 1
    border.color: activeFocus ? Color.accent : Style.normalBorderColor
    activeFocusOnTab: enabled
    Accessible.role: Accessible.Button
    Accessible.name: root.recording ? "Cancel changing the shortcut" : "Change the shortcut, now " + root.parts.join(" ")
    Accessible.onPressAction: root.press()

    Keys.onPressed: event => {
      if (!root.recording) {
        if (event.key === Qt.Key_Space || event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
          root.press()
          event.accepted = true
        }
        return
      }
      if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab) return
      event.accepted = true
      if (!event.isAutoRepeat) root.captured(event.key, event.modifiers)
    }
    onActiveFocusChanged: if (!activeFocus && root.recording) root.cancel()

    Label {
      id: label
      anchors.centerIn: parent
      text: root.recording ? "Cancel" : "Change"
      color: Color.foreground
      font.pixelSize: Style.font.body
    }

    MouseArea {
      id: mouse
      anchors.fill: parent
      enabled: button.enabled
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: {
        button.forceActiveFocus()
        root.press()
      }
    }
  }
}
