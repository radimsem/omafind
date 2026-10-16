import QtQuick
import qs.Commons
import "." as Plugin

// A row of fact tokens: a dim key, then its value. `tone` is plain, hit, warn or strong.
Row {
  id: root

  property var tokens: []
  property real fontSize: Style.font.bodySmall

  spacing: Style.space(14)
  clip: true

  Repeater {
    model: root.tokens

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
        text: modelData.v
        textFormat: Text.PlainText
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
