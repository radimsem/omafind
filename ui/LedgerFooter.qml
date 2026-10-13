import QtQuick
import qs.Commons
import ".." as Plugin

// `.ledger`: Found − Left out = Kept, from lib/ledger.js footer(). Buttons follow in the caller's row.
Row {
  id: root

  // {found, leftOut, kept, leftSub, keptLabel, keptSub}
  property var footer: null

  spacing: Style.space(14)

  component Figure: Row {
    id: figure
    property string label: ""
    property string value: ""
    property string sub: ""
    property color tone: Color.foreground
    spacing: Style.space(8)

    Text {
      anchors.baseline: number.baseline
      text: figure.label
      textFormat: Text.PlainText
      color: Plugin.Tokens.dim
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      font.capitalization: Font.AllUppercase
      font.letterSpacing: Style.font.caption * Plugin.Tokens.tracking
    }

    Text {
      id: number
      // Three characters wide at least, so the figures do not jump as they change.
      width: Math.max(implicitWidth, metrics.width)
      horizontalAlignment: Text.AlignRight
      text: figure.value
      textFormat: Text.PlainText
      color: figure.tone
      font.family: Style.font.family
      font.pixelSize: Style.font.iconLarge
      font.bold: true

      TextMetrics {
        id: metrics
        font: number.font
        text: "000"
      }
    }

    Text {
      anchors.baseline: number.baseline
      visible: figure.sub !== ""
      text: figure.sub
      textFormat: Text.PlainText
      color: Plugin.Tokens.dim
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }
  }

  component Operator: Text {
    anchors.verticalCenter: parent.verticalCenter
    textFormat: Text.PlainText
    color: Plugin.Tokens.dim
    font.family: Style.font.family
    font.pixelSize: Style.font.heading
  }

  Figure {
    anchors.verticalCenter: parent.verticalCenter
    label: "Found"
    value: root.footer ? root.footer.found : ""
  }

  Operator { text: "−" }

  Figure {
    anchors.verticalCenter: parent.verticalCenter
    label: "Left out"
    value: root.footer ? root.footer.leftOut : ""
    sub: root.footer ? root.footer.leftSub : ""
    tone: Color.urgent
  }

  Operator { text: "=" }

  Figure {
    anchors.verticalCenter: parent.verticalCenter
    label: root.footer ? root.footer.keptLabel : ""
    value: root.footer ? root.footer.kept : ""
    sub: root.footer ? root.footer.keptSub : ""
    tone: Plugin.Palette.green
  }
}
