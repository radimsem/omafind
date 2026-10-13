import QtQuick
import qs.Commons

// `.btn-acc` (primary), `.btn-pri` (primary and neutral) and `.btn-sec` from the boards.
// `flash` shows the 260 ms press before the overlay closes.
Rectangle {
  id: root

  property string text: ""
  property bool primary: false
  // Setup's `.btn-pri`: a foreground fill instead of the accent.
  property bool neutral: false
  property bool flash: false
  property real buttonHeight: Style.space(32)
  property int fontSize: Style.font.body
  property string icon: ""
  // Setup buttons take Tab focus and answer Enter and Space; search buttons stay mouse only.
  property bool focusable: false
  // A secondary button that toggles something open keeps the pressed fill while it is open.
  property bool active: false

  signal clicked()

  readonly property bool down: flash || (mouse.pressed && enabled)
  readonly property color fill: neutral ? Color.foreground : Color.accent

  implicitWidth: content.implicitWidth + 2 * Style.space(primary && !neutral ? 16 : 14)
  implicitHeight: buttonHeight
  radius: Style.cornerRadius
  opacity: enabled ? 1 : 0.4
  // Without a layer each child fades on its own and the label shows through the fill.
  layer.enabled: opacity < 1
  color: primary ? fill
    : down || active ? Style.selectedFill
    : mouse.containsMouse && enabled ? Style.hoverFill
    : "transparent"
  border.width: primary ? 0 : 1
  border.color: Style.normalBorderColor
  transform: Translate { y: root.down ? 1 : 0 }
  activeFocusOnTab: focusable && enabled
  Accessible.role: Accessible.Button
  Accessible.name: text

  Behavior on color { ColorAnimation { duration: root.down ? 70 : 140 } }
  Behavior on opacity { NumberAnimation { duration: 160 } }

  Keys.onPressed: event => {
    if (root.enabled && (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space)) {
      root.clicked()
      event.accepted = true
    }
  }

  // The canvas darkens the pressed primary to 0.78 brightness.
  Rectangle {
    anchors.fill: parent
    radius: parent.radius
    color: Color.background
    opacity: root.primary && root.down ? 0.22 : 0
    Behavior on opacity { NumberAnimation { duration: root.down ? 70 : 140 } }
  }

  Row {
    id: content
    anchors.centerIn: parent
    spacing: Style.space(8)

    Icon {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.icon !== ""
      name: root.icon
      size: Style.space(12)
      color: label.color
    }

    Text {
      id: label
      anchors.verticalCenter: parent.verticalCenter
      text: root.text
      textFormat: Text.PlainText
      color: root.primary ? Color.background : Color.foreground
      font.family: Style.font.family
      font.pixelSize: root.fontSize
      font.bold: root.primary
    }
  }

  Rectangle {
    anchors.fill: parent
    visible: root.activeFocus
    radius: parent.radius
    color: "transparent"
    border.width: 1
    border.color: Color.accent
  }

  MouseArea {
    id: mouse
    anchors.fill: parent
    hoverEnabled: true
    enabled: root.enabled
    cursorShape: Qt.PointingHandCursor
    onClicked: {
      if (root.focusable) root.forceActiveFocus()
      root.clicked()
    }
  }
}
