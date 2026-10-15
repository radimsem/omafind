import QtQuick
import qs.Commons
import ".." as Plugin

Text {
  renderType: Text.NativeRendering
  textFormat: Text.PlainText
  color: Plugin.Tokens.fg2
  font.family: Style.font.family
  font.pixelSize: Style.font.bodySmall
}
