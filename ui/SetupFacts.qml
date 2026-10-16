import QtQuick
import qs.Commons
import "." as Plugin

// Fact tokens for setup: Facts.qml plus a settable gap and `<b>` runs inside a value
// (`selected <b>1,209</b> files`), drawn in the foreground and bold as `.fx .v b`.
Row {
  id: root

  property var tokens: []
  property real fontSize: Style.font.bodySmall
  property real gap: Style.space(14)

  function escaped(value) {
    return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  }

  function rich(value) {
    var parts = String(value).split(/<b>|<\/b>/)
    var out = ""
    for (var i = 0; i < parts.length; i++)
      out += i % 2 ? "<b><font color=\"" + Color.foreground + "\">" + escaped(parts[i]) + "</font></b>" : escaped(parts[i])
    return out
  }

  spacing: gap
  clip: true
  // A Row has no baseline of its own; this lets callers anchor the facts by baseline.
  baselineOffset: metrics.ascent

  FontMetrics {
    id: metrics
    font.family: Style.font.family
    font.pixelSize: root.fontSize
  }

  Repeater {
    model: root.tokens || []

    delegate: Row {
      required property var modelData
      spacing: Style.space(5)

      Label {
        text: modelData.k
        textFormat: Text.PlainText
        color: Plugin.Tokens.dim
        font.family: Style.font.family
        font.pixelSize: root.fontSize
      }

      Label {
        readonly property string value: modelData.v === undefined || modelData.v === null ? "" : String(modelData.v)
        visible: value !== ""
        text: value.indexOf("<b>") >= 0 ? root.rich(value) : value
        textFormat: value.indexOf("<b>") >= 0 ? Text.StyledText : Text.PlainText
        color: modelData.tone === "hit" ? Color.accent
          : modelData.tone === "warn" ? Plugin.Palette.yellow
          : modelData.tone === "strong" ? Color.foreground
          : Plugin.Tokens.fg2
        font.family: Style.font.family
        font.pixelSize: root.fontSize
        font.bold: modelData.tone === "strong"
      }
    }
  }
}
