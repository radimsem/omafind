import QtQuick
import qs.Commons
import ".." as Plugin

// `.steps`: number box, label and a 48 px dash per step. Model from lib/setup.js chips(step).
Row {
  id: root

  property var chips: []

  spacing: Style.space(10)

  Repeater {
    model: root.chips

    delegate: Row {
      id: chip
      required property var modelData
      required property int index
      readonly property bool done: modelData.state === "done"
      readonly property bool cur: modelData.state === "cur"
      spacing: Style.space(8)

      Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        width: Style.space(20)
        height: width
        radius: Style.cornerRadius
        color: chip.done ? Util.alpha(Plugin.Palette.green, 0.16) : "transparent"
        border.width: chip.done ? 0 : 1
        border.color: chip.cur ? Color.accent : Style.normalBorderColor
        Behavior on color { ColorAnimation { duration: 160 } }
        Behavior on border.color { ColorAnimation { duration: 160 } }

        Text {
          anchors.centerIn: parent
          text: chip.modelData.mark
          textFormat: Text.PlainText
          color: chip.done ? Plugin.Palette.green : chip.cur ? Color.accent : Plugin.Tokens.dim
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          font.bold: true
          Behavior on color { ColorAnimation { duration: 160 } }
        }
      }

      Text {
        anchors.verticalCenter: parent.verticalCenter
        text: chip.modelData.label
        textFormat: Text.PlainText
        color: chip.cur ? Color.foreground : Plugin.Tokens.dim
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        Behavior on color { ColorAnimation { duration: 160 } }
      }

      Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        visible: chip.index < root.chips.length - 1
        width: Style.space(48)
        height: 1
        color: Plugin.Tokens.sep
      }
    }
  }
}
