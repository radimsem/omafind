import QtQuick
import qs.Commons
import ".." as Plugin

// `.sp-q`: search icon, the query with its prefix in accent, and the status slot.
Item {
  id: root

  property string prefix: ""
  property bool code: false
  property string status: ""
  property bool spinning: false
  readonly property alias text: input.text
  readonly property alias input: input

  signal keyPressed(var event)

  function setText(value) {
    input.text = value
    input.cursorPosition = value.length
  }

  function escaped(value) {
    return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/ /g, "&nbsp;")
  }

  implicitHeight: Plugin.Tokens.queryHeight

  Icon {
    id: icon
    anchors.left: parent.left
    anchors.leftMargin: Style.space(22)
    anchors.verticalCenter: parent.verticalCenter
    name: root.code ? "code" : "search"
    size: Style.space(22)
    strokeWidth: 2
    color: Color.accent
  }

  Item {
    id: field
    anchors.left: icon.right
    anchors.leftMargin: Style.space(14)
    anchors.right: statusRow.left
    anchors.rightMargin: Style.space(14)
    anchors.verticalCenter: parent.verticalCenter
    height: Style.space(30)
    clip: true
    // TextInput's internal scroll has no offset property; cursor geometry changes when it scrolls.
    readonly property real contentX: {
      input.cursorRectangle
      input.cursorPosition
      input.text
      input.width
      return -input.positionToRectangle(0).x
    }

    TextInput {
      id: input
      objectName: "omafindQueryInput"
      anchors.fill: parent
      verticalAlignment: TextInput.AlignVCenter
      // The visible text is drawn by `styled` so the prefix can take the accent.
      color: "transparent"
      selectionColor: Util.alpha(Color.accent, 0.35)
      selectedTextColor: Color.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.display
      focus: true
      selectByMouse: true
      Keys.priority: Keys.BeforeItem
      Keys.onPressed: event => root.keyPressed(event)

      cursorDelegate: Rectangle {
        width: Style.space(10)
        height: Style.space(24)
        color: Color.accent
        visible: input.activeFocus

        SequentialAnimation on opacity {
          loops: Animation.Infinite
          running: input.activeFocus
          PropertyAction { value: 1 }
          PauseAnimation { duration: 550 }
          PropertyAction { value: 0 }
          PauseAnimation { duration: 550 }
        }
      }
    }

    Text {
      id: styled
      x: -field.contentX
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.StyledText
      text: {
        var value = input.text
        var head = root.prefix && value.indexOf(root.prefix) === 0 ? root.prefix : ""
        return (head ? "<font color=\"" + Color.accent + "\">" + root.escaped(head) + "</font>" : "")
          + root.escaped(value.slice(head.length))
      }
      color: Color.foreground
      font: input.font
    }

    Text {
      visible: input.text === ""
      x: Style.space(10) + Style.space(6)
      anchors.verticalCenter: parent.verticalCenter
      text: "Describe what is in the file"
      textFormat: Text.PlainText
      color: Plugin.Tokens.placeholder
      font: input.font
    }
  }

  Row {
    id: statusRow
    anchors.right: parent.right
    anchors.rightMargin: Style.space(22)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(8)

    Spinner {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.spinning
      running: root.spinning
    }

    Text {
      anchors.verticalCenter: parent.verticalCenter
      text: root.status
      textFormat: Text.PlainText
      color: Plugin.Tokens.dim
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }
  }
}
