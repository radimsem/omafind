import QtQuick
import qs.Commons
import ".." as Plugin

// `.p-head`: an optional crumb, the title, a sentence or fact line beneath, and `Step N of 3` right.
Item {
  id: root

  property string crumb: ""
  property string crumbLeaf: ""
  property string title: ""
  property string subtitle: ""
  property var facts: []
  property bool spinning: false
  property string stepText: ""

  implicitHeight: column.implicitHeight + Style.space(6)

  Column {
    id: column
    y: Style.space(2)
    width: parent.width - step.implicitWidth - Style.space(12)
    spacing: Style.space(4)

    Row {
      visible: root.crumb !== ""
      spacing: Style.space(6)

      Label {
        anchors.verticalCenter: parent.verticalCenter
        text: root.crumb
        textFormat: Text.PlainText
        color: Plugin.Tokens.dim
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }

      Icon {
        anchors.verticalCenter: parent.verticalCenter
        name: "twisty"
        size: Style.space(10)
        color: Plugin.Tokens.dim
      }

      Label {
        anchors.verticalCenter: parent.verticalCenter
        text: root.crumbLeaf
        textFormat: Text.PlainText
        color: Plugin.Tokens.dim
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }
    }

    Label {
      text: root.title
      textFormat: Text.PlainText
      color: Color.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.heading
      font.bold: true
    }

    Item {
      width: parent.width
      height: Math.max(sentence.implicitHeight, factRow.implicitHeight)

      Label {
        id: sentence
        width: parent.width
        visible: root.subtitle !== ""
        text: root.subtitle
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: Plugin.Tokens.dim
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }

      Row {
        visible: root.subtitle === ""
        width: parent.width
        spacing: Style.space(8)

        Spinner {
          anchors.verticalCenter: parent.verticalCenter
          visible: root.spinning
          running: root.spinning
        }

        SetupFacts {
          id: factRow
          anchors.verticalCenter: parent.verticalCenter
          width: Math.min(implicitWidth, parent.width)
          tokens: root.facts
          fontSize: Style.font.body
        }
      }
    }
  }

  Label {
    id: step
    anchors.right: parent.right
    // The tree header pins the label to the top; the step header centres it.
    y: root.crumb !== "" ? Style.space(2) : Math.round((root.implicitHeight - implicitHeight) / 2)
    text: root.stepText
    textFormat: Text.PlainText
    color: Plugin.Tokens.dim
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
    font.capitalization: Font.AllUppercase
    font.letterSpacing: Math.round(Style.font.bodySmall * Plugin.Tokens.tracking)
  }
}
