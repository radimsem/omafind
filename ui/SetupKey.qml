import QtQuick
import qs.Commons
import "." as Plugin

// `.kbd` at a size of the caller's choosing: 26 high and 12 px for the shortcut, 16 high and 9 px in a tree row.
Rectangle {
  id: root

  property string text: ""
  property int fontSize: Style.font.bodySmall
  property real padding: Style.space(5)

  implicitWidth: Math.max(implicitHeight, label.implicitWidth + 2 * padding)
  implicitHeight: Style.space(18)
  radius: Style.cornerRadius
  color: "transparent"
  border.width: 1
  border.color: Style.normalBorderColor

  Label {
    id: label
    anchors.centerIn: parent
    text: root.text
    textFormat: Text.PlainText
    color: Plugin.Tokens.fg2
    font.family: Style.font.family
    font.pixelSize: root.fontSize
  }
}
