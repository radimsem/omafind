import QtQuick
import qs.Commons
import ".." as Plugin

// `.bigprog`, `.bar2` and `.fb`: a hover-fill track, an accent fill that turns green when done.
Rectangle {
  id: root

  property real fraction: 0
  property bool done: false

  implicitHeight: Style.space(6)
  color: Style.hoverFill
  clip: true

  Rectangle {
    height: parent.height
    width: parent.width * Math.max(0, Math.min(1, root.fraction))
    color: root.done ? Plugin.Palette.green : Color.accent
    Behavior on width { NumberAnimation { duration: 300; easing.type: Easing.Linear } }
    Behavior on color { ColorAnimation { duration: 200 } }
  }
}
