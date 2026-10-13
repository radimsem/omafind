import QtQuick
import qs.Commons
import ".." as Plugin

// `.switch`: 42 by 22 track with a 14 px knob. Rounded themes round both, as the shell does.
Rectangle {
  id: root

  property bool checked: false
  property string label: ""

  signal toggled()

  readonly property bool rounded: Style.cornerRadius > 0

  implicitWidth: Style.space(42)
  implicitHeight: Style.space(22)
  radius: rounded ? height / 2 : 0
  color: checked ? Color.foreground : "transparent"
  border.width: 1
  border.color: checked ? Color.foreground : Style.normalBorderColor
  activeFocusOnTab: enabled
  Accessible.role: Accessible.CheckBox
  Accessible.name: label
  Accessible.checked: checked

  Behavior on color { ColorAnimation { duration: 120 } }
  Behavior on border.color { ColorAnimation { duration: 120 } }

  Keys.onPressed: event => {
    if (root.enabled && (event.key === Qt.Key_Space || event.key === Qt.Key_Return || event.key === Qt.Key_Enter)) {
      root.toggled()
      event.accepted = true
    }
  }

  Rectangle {
    x: root.checked ? Style.space(23) : Style.space(3)
    anchors.verticalCenter: parent.verticalCenter
    width: Style.space(14)
    height: width
    radius: root.rounded ? width / 2 : 0
    color: root.checked ? Color.background : Plugin.Tokens.dim
    Behavior on x { NumberAnimation { duration: 120; easing.type: Easing.BezierSpline; easing.bezierCurve: Plugin.Tokens.ease } }
    Behavior on color { ColorAnimation { duration: 120 } }
  }

  // Focus outline 1 px, offset 3.
  Rectangle {
    anchors.fill: parent
    anchors.margins: -Style.space(4)
    visible: root.activeFocus
    radius: root.rounded ? height / 2 : 0
    color: "transparent"
    border.width: 1
    border.color: Color.accent
  }

  MouseArea {
    anchors.fill: parent
    enabled: root.enabled
    cursorShape: Qt.PointingHandCursor
    onClicked: {
      root.forceActiveFocus()
      root.toggled()
    }
  }
}
