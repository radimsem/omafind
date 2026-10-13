import QtQuick
import qs.Commons
import ".." as Plugin

// `.ban`: a yellow wash, a warning glyph, a bold lead, the sentence and a Retry button.
Rectangle {
  id: root

  property string lead: ""
  property string text: ""
  property string action: "Retry"

  signal triggered()

  function escaped(value) {
    return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  }

  implicitHeight: Math.max(Style.space(44), body.implicitHeight + 2 * Style.space(9))
  color: Util.alpha(Plugin.Palette.yellow, 0.08)

  Icon {
    id: glyph
    anchors.left: parent.left
    anchors.leftMargin: Style.space(16)
    anchors.verticalCenter: parent.verticalCenter
    name: "warn"
    color: Plugin.Palette.yellow
  }

  Text {
    id: body
    anchors.left: glyph.right
    anchors.leftMargin: Style.space(10)
    anchors.right: button.left
    anchors.rightMargin: Style.space(10)
    anchors.verticalCenter: parent.verticalCenter
    wrapMode: Text.Wrap
    textFormat: Text.StyledText
    text: (root.lead ? "<b><font color=\"" + Color.foreground + "\">" + root.escaped(root.lead) + "</font></b> " : "") + root.escaped(root.text)
    color: Plugin.Tokens.fg2
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }

  ActionButton {
    id: button
    anchors.right: parent.right
    anchors.rightMargin: Style.space(16)
    anchors.verticalCenter: parent.verticalCenter
    buttonHeight: Style.space(26)
    text: root.action
    onClicked: root.triggered()
  }
}
