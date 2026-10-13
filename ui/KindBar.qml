import QtQuick
import qs.Commons
import ".." as Plugin

// `.cmp`: 4 px composition bar, segments sized by file count in kind colors with 1 px gaps.
// With no segments it is the 18 px hatched `.nil` bar of a folder with no kind.
Item {
  id: root

  // [{kind, n}] from lib/tree.js rows.
  property var segments: []
  property real barWidth: Style.space(40)

  readonly property bool nil: !segments || segments.length === 0
  readonly property real total: {
    var sum = 0
    for (var i = 0; i < (segments || []).length; i++) sum += segments[i].n
    return sum
  }

  function colorOf(kind) {
    return kind === "pdf" ? Color.urgent
      : kind === "image" ? Plugin.Palette.cyan
      : kind === "video" ? Color.accent
      : kind === "audio" ? Plugin.Palette.yellow
      : Plugin.Tokens.fg2
  }

  implicitWidth: nil ? Style.space(18) : barWidth
  implicitHeight: Style.space(4)
  Behavior on implicitWidth { NumberAnimation { duration: 220; easing.type: Easing.BezierSpline; easing.bezierCurve: Plugin.Tokens.ease } }

  Row {
    visible: !root.nil
    anchors.fill: parent
    spacing: 1

    Repeater {
      model: root.nil ? [] : root.segments

      delegate: Rectangle {
        required property var modelData
        height: root.height
        width: Math.max(1, (root.width - (root.segments.length - 1)) * modelData.n / Math.max(1, root.total))
        color: root.colorOf(modelData.kind)
      }
    }
  }

  Hatch {
    visible: root.nil
    anchors.fill: parent
    spacing: 3
    alpha: 0.25
  }

  Rectangle {
    visible: root.nil
    anchors.fill: parent
    color: "transparent"
    border.width: 1
    border.color: Util.alpha(Color.foreground, 0.3)
  }
}
