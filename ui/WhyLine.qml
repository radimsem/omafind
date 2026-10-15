import QtQuick
import qs.Commons
import ".." as Plugin
import "../lib/format.js" as Format

// `.pv-why`: the computed facts behind a result. A words-leg hit shows the `Aa` glyph and its snippet.
Item {
  id: root

  property var item: ({})

  readonly property bool offline: item.offline === true
  readonly property var runs: Format.snippetRuns(item.snippet || [])
  readonly property bool wordsHit: item.leg === "words" && runs.some(run => run.m)
  // The boards color only `hits` in accent and show `opener` beside the actions, not here.
  readonly property var tokens: Format.why(item, null).filter(token => token.k !== "opener")
    .map(token => ({k: token.k, v: token.v, tone: token.k === "hits" ? "hit" : "plain"}))

  function escaped(value) {
    return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  }

  function snippetMarkup() {
    var out = ""
    for (var i = 0; i < runs.length; i++) {
      out += runs[i].m ? "<b><font color=\"" + Color.foreground + "\">" + escaped(runs[i].t) + "</font></b>"
        : escaped(runs[i].t)
    }
    return out
  }

  implicitHeight: offline ? offlineRow.implicitHeight : wordsHit ? wordsRow.implicitHeight : factRow.implicitHeight

  Row {
    id: offlineRow
    visible: root.offline
    width: parent.width
    spacing: Style.space(8)

    Icon {
      anchors.verticalCenter: parent.verticalCenter
      name: "drive"
      size: Style.space(15)
      color: Plugin.Palette.yellow
    }

    Label {
      anchors.verticalCenter: parent.verticalCenter
      width: parent.width - Style.space(23)
      text: (root.item.label || "This drive") + " is not connected. Connect it to open this file."
      textFormat: Text.PlainText
      wrapMode: Text.Wrap
      color: Plugin.Palette.yellow
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }
  }

  Row {
    id: factRow
    visible: !root.offline && !root.wordsHit
    width: parent.width
    spacing: Style.space(8)

    Icon {
      anchors.verticalCenter: parent.verticalCenter
      name: "why"
      size: Style.space(15)
      color: Color.accent
    }

    Facts {
      anchors.verticalCenter: parent.verticalCenter
      width: Math.min(implicitWidth, parent.width - Style.space(23))
      tokens: root.tokens
      fontSize: Style.font.bodySmall
      spacing: Style.space(16)
    }
  }

  Row {
    id: wordsRow
    visible: !root.offline && root.wordsHit
    width: parent.width
    spacing: Style.space(8)

    Label {
      width: Style.space(15)
      text: "Aa"
      textFormat: Text.PlainText
      color: Color.accent
      font.family: Style.font.family
      font.pixelSize: Style.font.subtitle
      font.bold: true
    }

    Column {
      width: parent.width - Style.space(23)
      spacing: Style.space(6)

      Facts {
        width: Math.min(implicitWidth, parent.width)
        tokens: root.tokens
        fontSize: Style.font.bodySmall
        spacing: Style.space(16)
      }

      Label {
        width: parent.width
        text: root.snippetMarkup()
        textFormat: Text.StyledText
        elide: Text.ElideRight
        maximumLineCount: 1
        color: Plugin.Tokens.dim
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }
    }
  }
}
