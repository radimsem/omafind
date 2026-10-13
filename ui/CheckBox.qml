import QtQuick
import qs.Commons

// `.cb`: 16 px tri-state check with a fixed 2 px radius. `mark` is "on", "mixed" or "off".
Rectangle {
  id: root

  property string mark: "off"
  property string label: ""

  signal toggled()

  readonly property bool on: mark === "on"
  readonly property bool mixed: mark === "mixed"

  implicitWidth: Style.space(16)
  implicitHeight: Style.space(16)
  radius: 2
  color: on ? Color.accent : mixed ? Util.alpha(Color.accent, 0.2) : "transparent"
  border.width: 1.5
  border.color: on || mixed ? Color.accent : Style.normalBorderColor
  activeFocusOnTab: enabled
  Accessible.role: Accessible.CheckBox
  Accessible.name: label
  Accessible.checked: on

  Behavior on color { ColorAnimation { duration: 100 } }
  Behavior on border.color { ColorAnimation { duration: 100 } }

  Keys.onPressed: event => {
    if (root.enabled && (event.key === Qt.Key_Space || event.key === Qt.Key_Return || event.key === Qt.Key_Enter)) {
      root.toggled()
      event.accepted = true
    }
  }

  Icon {
    anchors.centerIn: parent
    name: root.mixed ? "dash" : "check"
    size: Style.space(11)
    strokeWidth: root.mixed ? 3 : 2.4
    color: root.mixed ? Color.accent : Color.background
    opacity: root.on || root.mixed ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 100 } }
  }

  // Focus ring outside the box, as the board's pressed state.
  Rectangle {
    anchors.fill: parent
    anchors.margins: -Style.space(3)
    visible: root.activeFocus
    radius: 2
    color: "transparent"
    border.width: 1
    border.color: Color.accent
  }

  MouseArea {
    anchors.fill: parent
    anchors.margins: -Style.space(6)
    enabled: root.enabled
    cursorShape: Qt.PointingHandCursor
    onClicked: {
      root.forceActiveFocus()
      root.toggled()
    }
  }
}
