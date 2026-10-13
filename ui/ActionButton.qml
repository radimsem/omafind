import QtQuick
import qs.Commons

// `.btn-acc` (primary) and `.btn-sec` from the boards. `flash` shows the 260 ms press before the overlay closes.
Rectangle {
  id: root

  property string text: ""
  property bool primary: false
  property bool flash: false
  property real buttonHeight: Style.space(32)

  signal clicked()

  readonly property bool down: flash || (mouse.pressed && enabled)

  implicitWidth: label.implicitWidth + 2 * Style.space(primary ? 16 : 14)
  implicitHeight: buttonHeight
  radius: Style.cornerRadius
  opacity: enabled ? 1 : 0.4
  color: primary ? Color.accent
    : down ? Style.selectedFill
    : mouse.containsMouse && enabled ? Style.hoverFill
    : "transparent"
  border.width: primary ? 0 : 1
  border.color: Style.normalBorderColor
  transform: Translate { y: root.down ? 1 : 0 }

  Behavior on color { ColorAnimation { duration: root.down ? 70 : 140 } }

  // The canvas darkens the pressed primary to 0.78 brightness.
  Rectangle {
    anchors.fill: parent
    radius: parent.radius
    color: Color.background
    opacity: root.primary && root.down ? 0.22 : 0
    Behavior on opacity { NumberAnimation { duration: root.down ? 70 : 140 } }
  }

  Text {
    id: label
    anchors.centerIn: parent
    text: root.text
    textFormat: Text.PlainText
    color: root.primary ? Color.background : Color.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.body
    font.bold: root.primary
  }

  MouseArea {
    id: mouse
    anchors.fill: parent
    hoverEnabled: true
    enabled: root.enabled
    cursorShape: Qt.PointingHandCursor
    onClicked: root.clicked()
  }
}
