import QtQuick
import qs.Commons
import ".." as Plugin

// `.sec-h`: uppercase section name with its count, 30 high in the moving list.
Item {
  id: root

  property string title: ""
  property int count: 0

  implicitHeight: Plugin.Tokens.headerHeight

  Row {
    anchors.left: parent.left
    anchors.leftMargin: Style.space(10)
    anchors.top: parent.top
    anchors.topMargin: Style.space(12)
    anchors.bottom: parent.bottom
    anchors.bottomMargin: Style.space(6)
    spacing: Style.space(8)

    Text {
      text: root.title.toUpperCase()
      textFormat: Text.PlainText
      color: Plugin.Tokens.dim
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      font.bold: true
      font.letterSpacing: Style.font.caption * 0.1
    }

    Text {
      text: root.count
      textFormat: Text.PlainText
      color: Plugin.Tokens.dim
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }
  }
}
