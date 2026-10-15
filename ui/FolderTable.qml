import QtQuick
import qs.Commons
import ".." as Plugin

// `.dt-h`: the folder table header, and the column geometry every `.dt-r` row lays out against.
// Columns: check, folder (flexible), Text, PDF, Images, Video, Audio, Index, Time, action.
Item {
  id: root

  property string folderLabel: "Folder"

  readonly property int gap: Plugin.Tokens.tableGap
  readonly property int padding: Plugin.Tokens.tablePadding
  readonly property var widths: {
    var columns = Plugin.Tokens.tableColumns
    var fixed = 0
    for (var i = 0; i < columns.length; i++) fixed += columns[i]
    var flex = Math.max(0, width - 2 * padding - fixed - gap * (columns.length - 1))
    return columns.map((w, i) => i === 1 ? flex : w)
  }
  readonly property var labels: ["", folderLabel, "Text", "PDF", "Images", "Video", "Audio", "Index", "Time", ""]

  function cellX(index) {
    var x = padding
    for (var i = 0; i < index; i++) x += widths[i] + gap
    return x
  }

  implicitHeight: Plugin.Tokens.tableHeader

  Repeater {
    model: root.labels

    delegate: Row {
      required property string modelData
      required property int index
      readonly property bool numeric: index >= 2 && index <= 8
      x: numeric ? root.cellX(index) + root.widths[index] - implicitWidth : root.cellX(index)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(6)

      Label {
        anchors.verticalCenter: parent.verticalCenter
        text: parent.modelData
        textFormat: Text.PlainText
        color: Plugin.Tokens.dim
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        font.capitalization: Font.AllUppercase
        font.letterSpacing: Math.round(Style.font.bodySmall * Plugin.Tokens.tracking)
      }
    }
  }

  Rectangle {
    anchors.bottom: parent.bottom
    width: parent.width
    height: 1
    color: Plugin.Tokens.sep
  }
}
