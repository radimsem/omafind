import QtQuick
import qs.Commons
import "." as Plugin
import "../lib/setup.js" as Setup

Column {
  id: root

  property var progress: null
  property real labelWidth: Style.space(80)
  property real textWidth: Style.space(190)

  spacing: Style.space(8)

  Repeater {
    model: Setup.kindRows(root.progress)

    delegate: Item {
      required property var modelData
      width: root.width
      height: kindLabel.implicitHeight

      Label {
        id: kindLabel
        width: root.labelWidth
        text: modelData.label
        font.pixelSize: Style.font.body
      }

      ProgressBar {
        x: root.labelWidth + Style.space(14)
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width - x - root.textWidth - Style.space(14)
        height: Style.space(6)
        fraction: modelData.fraction
        done: modelData.done
      }

      Label {
        anchors.right: parent.right
        width: root.textWidth
        horizontalAlignment: Text.AlignRight
        text: modelData.text
        color: Plugin.Tokens.dim
        font.pixelSize: Style.font.body
      }
    }
  }
}
