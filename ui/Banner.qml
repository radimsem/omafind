import QtQuick
import qs.Commons
import ".." as Plugin

// `.ban`: a yellow wash, a warning glyph, a bold lead, the sentence and a Retry button.
// With `tokens` the lead is followed by fact tokens before the sentence (the disk banner).
Rectangle {
  id: root

  property string lead: ""
  property string text: ""
  property var tokens: []
  // An empty action hides the button.
  property string action: "Retry"

  signal triggered()

  function escaped(value) {
    return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  }

  readonly property bool factual: !!tokens && tokens.length > 0

  implicitHeight: Math.max(Style.space(44), (factual ? factRow.implicitHeight : body.implicitHeight) + 2 * Style.space(9))
  color: Util.alpha(Plugin.Palette.yellow, 0.08)

  Icon {
    id: glyph
    anchors.left: parent.left
    anchors.leftMargin: Style.space(16)
    anchors.verticalCenter: parent.verticalCenter
    name: "warn"
    color: Plugin.Palette.yellow
  }

  Label {
    id: body
    visible: !root.factual
    anchors.left: glyph.right
    anchors.leftMargin: Style.space(10)
    anchors.right: button.visible ? button.left : parent.right
    anchors.rightMargin: Style.space(button.visible ? 10 : 16)
    anchors.verticalCenter: parent.verticalCenter
    wrapMode: Text.Wrap
    textFormat: Text.StyledText
    text: (root.lead ? "<b><font color=\"" + Color.foreground + "\">" + root.escaped(root.lead) + "</font></b> " : "") + root.escaped(root.text)
    color: Plugin.Tokens.fg2
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }

  Row {
    id: factRow
    visible: root.factual
    anchors.left: glyph.right
    anchors.leftMargin: Style.space(10)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(10)

    Label {
      anchors.verticalCenter: parent.verticalCenter
      text: root.lead
      textFormat: Text.PlainText
      color: Color.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.body
      font.bold: true
    }

    Facts {
      anchors.verticalCenter: parent.verticalCenter
      tokens: root.factual ? root.tokens : []
      fontSize: Style.font.body
    }

    Label {
      anchors.verticalCenter: parent.verticalCenter
      text: root.text
      textFormat: Text.PlainText
      color: Plugin.Tokens.fg2
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }
  }

  ActionButton {
    id: button
    visible: root.action !== ""
    anchors.right: parent.right
    anchors.rightMargin: Style.space(16)
    anchors.verticalCenter: parent.verticalCenter
    buttonHeight: Style.space(26)
    text: root.action
    onClicked: root.triggered()
  }
}
