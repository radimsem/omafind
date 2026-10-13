import QtQuick
import qs.Commons
import ".." as Plugin

// Board Empty: what omafind searches, and the six prefixes. A chip inserts its prefix.
Item {
  id: root

  signal prefixChosen(string prefix)

  readonly property var chips: [
    {p: "img:", label: "images"},
    {p: "pdf:", label: "PDF pages"},
    {p: "doc:", label: "notes and documents"},
    {p: "vid:", label: "video moments"},
    {p: "aud:", label: "audio moments"},
    {p: "code:", label: "code"}
  ]

  Column {
    anchors.centerIn: parent
    anchors.verticalCenterOffset: -Style.space(20)
    spacing: Style.space(12)

    Item {
      anchors.horizontalCenter: parent.horizontalCenter
      width: Style.space(36)
      height: Style.space(36 + 8)

      Icon {
        name: "search"
        size: Style.space(36)
        strokeWidth: 1.2
        color: Plugin.Tokens.dim
      }
    }

    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      text: "Search photos, screenshots, PDFs, notes, videos and recordings by what they contain."
      textFormat: Text.PlainText
      color: Color.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.heading
    }

    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      width: Math.min(implicitWidth, Style.space(640))
      horizontalAlignment: Text.AlignHCenter
      wrapMode: Text.Wrap
      lineHeight: Style.space(18)
      lineHeightMode: Text.FixedHeight
      text: "Type a description in any language. Start with a prefix to search one kind only."
      textFormat: Text.PlainText
      color: Plugin.Tokens.dim
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }

    Row {
      anchors.horizontalCenter: parent.horizontalCenter
      topPadding: Style.space(10)
      spacing: Style.space(8)

      Repeater {
        model: root.chips

        delegate: Rectangle {
          id: chip
          required property var modelData
          width: chipRow.implicitWidth + 2 * Style.space(10)
          height: Style.space(28)
          radius: Style.cornerRadius
          color: "transparent"
          border.width: 1
          border.color: mouse.containsMouse ? Plugin.Tokens.fg2 : Plugin.Tokens.sep
          Behavior on border.color { ColorAnimation { duration: 120 } }

          Row {
            id: chipRow
            anchors.centerIn: parent
            spacing: Style.space(8)

            Text {
              text: chip.modelData.p
              textFormat: Text.PlainText
              color: Color.accent
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
            }

            Text {
              text: chip.modelData.label
              textFormat: Text.PlainText
              color: Plugin.Tokens.fg2
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
            }
          }

          MouseArea {
            id: mouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.prefixChosen(chip.modelData.p)
          }
        }
      }
    }
  }
}
