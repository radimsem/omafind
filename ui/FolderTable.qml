import QtQuick
import qs.Commons
import ".." as Plugin

// `.dt-h`: the folder table header, and the column geometry every `.dt-r` row lays out against.
// Columns: check, folder (flexible), Text, PDF, Images, Video, Audio, Index, Time, action.
Item {
  id: root

  // Exclusions shows a 6 px kind dot before each count header.
  property bool kindDots: false
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
  readonly property var kinds: ["text", "pdf", "image", "video", "audio"]
  readonly property var labels: ["", folderLabel, "Text", "PDF", "Images", "Video", "Audio", "Index", "Time", ""]

  function cellX(index) {
    var x = padding
    for (var i = 0; i < index; i++) x += widths[i] + gap
    return x
  }

  // Index and Time together, where the hatched "not indexed" cell sits.
  function spanWidth(index, count) {
    var w = 0
    for (var i = index; i < index + count; i++) w += widths[i]
    return w + gap * (count - 1)
  }

  function kindColor(kind) {
    return kind === "pdf" ? Color.urgent
      : kind === "image" ? Plugin.Palette.cyan
      : kind === "video" ? Color.accent
      : kind === "audio" ? Plugin.Palette.yellow
      : Plugin.Tokens.fg2
  }

  implicitHeight: Plugin.Tokens.tableHeader

  Repeater {
    model: root.labels

    delegate: Row {
      required property string modelData
      required property int index
      readonly property bool numeric: index >= 2 && index <= 8
      readonly property bool dotted: root.kindDots && index >= 2 && index <= 6
      x: numeric ? root.cellX(index) + root.widths[index] - implicitWidth : root.cellX(index)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(6)

      Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        visible: parent.dotted
        width: Style.space(6)
        height: width
        color: parent.dotted ? root.kindColor(root.kinds[parent.index - 2]) : "transparent"
      }

      Text {
        anchors.verticalCenter: parent.verticalCenter
        text: parent.modelData
        textFormat: Text.PlainText
        color: Plugin.Tokens.dim
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        font.capitalization: Font.AllUppercase
        font.letterSpacing: Style.font.caption * Plugin.Tokens.tracking
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
