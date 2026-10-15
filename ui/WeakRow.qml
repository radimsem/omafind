import QtQuick
import qs.Commons
import ".." as Plugin
import "../lib/format.js" as Format

// `.wk` from board Code: a chevron and "5 weaker matches". Enter or a click folds and unfolds the weaker hits.
Rectangle {
  id: root

  property int count: 0
  property bool selected: false
  property bool expanded: false

  signal clicked()

  implicitHeight: Plugin.Tokens.weakHeight
  radius: Style.cornerRadius
  color: selected ? Plugin.Tokens.selectedRow : "transparent"
  border.width: selected ? 1 : 0
  border.color: Color.accent

  Behavior on color { ColorAnimation { duration: 100 } }

  Row {
    anchors.left: parent.left
    anchors.leftMargin: Style.space(10)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(8)

    Icon {
      anchors.verticalCenter: parent.verticalCenter
      name: "chevron"
      size: Style.space(12)
      strokeWidth: 2
      color: Plugin.Tokens.dim
      rotation: root.expanded ? 180 : 0
      Behavior on rotation { NumberAnimation { duration: 120 } }
    }

    Label {
      anchors.verticalCenter: parent.verticalCenter
      text: Format.count(root.count) + (root.count === 1 ? " weaker match" : " weaker matches")
      textFormat: Text.PlainText
      color: Plugin.Tokens.dim
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }
  }

  MouseArea {
    anchors.fill: parent
    cursorShape: Qt.PointingHandCursor
    onClicked: root.clicked()
  }
}
