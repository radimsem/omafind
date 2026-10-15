import QtQuick
import qs.Commons
import ".." as Plugin

// `.task`: a 22 px marker, the title over its fact line, and a value or fact tokens on the right.
// `mark` is ok, run, wait or failed; `valueTone` is ok, plain or fail.
Item {
  id: root

  property string mark: "wait"
  property string title: ""
  property var tokens: []
  property string value: ""
  property string valueTone: "plain"
  // Fact tokens in place of `value` (`got 512/865 MB · left ~1 min`).
  property var valueTokens: null
  property string buttonText: ""
  property bool buttonEnabled: true

  signal buttonClicked()

  implicitHeight: Math.max(Style.space(22), textColumn.implicitHeight, slot.implicitHeight)

  Rectangle {
    id: marker
    anchors.verticalCenter: parent.verticalCenter
    width: Style.space(22)
    height: width
    color: root.mark === "ok" ? Util.alpha(Plugin.Palette.green, 0.16)
      : root.mark === "run" ? Util.alpha(Color.accent, 0.12)
      : root.mark === "failed" ? Util.alpha(Color.urgent, 0.16)
      : "transparent"
    border.width: root.mark === "wait" ? 1 : 0
    border.color: Style.normalBorderColor
    Behavior on color { ColorAnimation { duration: 160 } }

    Spinner {
      anchors.centerIn: parent
      opacity: root.mark === "run" ? 1 : 0
      running: root.mark === "run"
      Behavior on opacity { NumberAnimation { duration: 120 } }
    }

    Icon {
      anchors.centerIn: parent
      name: root.mark === "failed" ? "x" : "check"
      size: Style.space(12)
      color: root.mark === "failed" ? Color.urgent : Plugin.Palette.green
      opacity: root.mark === "ok" || root.mark === "failed" ? 1 : 0
      Behavior on opacity { NumberAnimation { duration: 120 } }
    }
  }

  Column {
    id: textColumn
    anchors.left: marker.right
    anchors.leftMargin: Style.space(12)
    anchors.right: slot.left
    anchors.rightMargin: Style.space(12)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(2)

    Label {
      text: root.title
      textFormat: Text.PlainText
      color: Color.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.subtitle
      font.bold: true
    }

    SetupFacts {
      width: Math.min(implicitWidth, parent.width)
      tokens: root.tokens
      fontSize: Style.font.bodySmall
    }
  }

  Item {
    id: slot
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    implicitWidth: button.visible ? button.implicitWidth : facts.visible ? facts.implicitWidth : label.implicitWidth
    implicitHeight: button.visible ? button.implicitHeight : label.implicitHeight
    width: implicitWidth
    height: implicitHeight

    Label {
      id: label
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      visible: !root.valueTokens && !button.visible
      text: root.value
      textFormat: Text.PlainText
      color: root.valueTone === "fail" ? Color.urgent : Plugin.Tokens.fg2
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      Behavior on color { ColorAnimation { duration: 160 } }
    }

    SetupFacts {
      id: facts
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      visible: !!root.valueTokens && !button.visible
      tokens: root.valueTokens || []
      fontSize: Style.font.bodySmall
    }

    ActionButton {
      id: button
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      visible: root.buttonText !== ""
      text: root.buttonText
      enabled: root.buttonEnabled
      focusable: true
      buttonHeight: Style.space(28)
      onClicked: root.buttonClicked()
    }
  }
}
