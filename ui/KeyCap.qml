import QtQuick
import qs.Commons
import ".." as Plugin

Rectangle {
  id: cap

  property string text: ""

  implicitWidth: Math.max(Style.space(18), capLabel.implicitWidth + 2 * Style.space(5))
  implicitHeight: Style.space(18)
  radius: Style.cornerRadius
  color: "transparent"
  border.width: 1
  border.color: Style.normalBorderColor

  Label {
    id: capLabel
    anchors.centerIn: parent
    text: cap.text
    textFormat: Text.PlainText
    color: Plugin.Tokens.fg2
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
  }
}
