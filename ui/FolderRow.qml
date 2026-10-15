import QtQuick
import qs.Commons
import ".." as Plugin

// `.dt-r`: one folder table row, laid out on a FolderTable's columns.
Item {
  id: root

  property var table: null
  // The folder this row stands for; the screenshot harness finds rows by it.
  property string path: ""
  property real rowHeight: Plugin.Tokens.tableRow
  // Check column: "on", "mixed", "off", or "" for an empty cell.
  property string check: ""
  property string checkLabel: ""
  property int depth: 0
  // "none" (no twisty column), "leaf" (its space only), "open" or "closed".
  property string twisty: "none"
  property string name: ""
  property string rule: ""
  property var facts: []
  // Five kind cells: [{n, cut}] for numbers, or `dash` for repositories.
  property var cells: []
  property bool dash: false
  property real numSize: Style.font.body
  property string indexText: ""
  property string timeText: ""
  property bool pending: false
  // Action column: "" or "code".
  property string action: ""
  property bool actionActive: false
  property string actionLabel: ""
  // Row fill: "" or "on" (checked).
  property string fill: ""
  property bool hairline: true
  property real pathGap: Style.space(2)

  signal toggled()
  signal actionClicked()
  signal twistyClicked()

  readonly property bool focused: check !== "" && checkBox.activeFocus
  readonly property real indent: Style.space(18)

  function focusCheck() {
    checkBox.forceActiveFocus()
  }

  function formatted(n) {
    return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",")
  }

  implicitHeight: rowHeight

  Rectangle {
    id: back
    width: parent.width
    height: root.rowHeight
    color: root.fill === "on" ? Util.alpha(Color.accent, 0.06)
      : "transparent"
    Behavior on color { ColorAnimation { duration: 160 } }

    Rectangle {
      anchors.fill: parent
      color: "transparent"
      border.width: 1
      border.color: Color.accent
      opacity: root.focused ? 1 : 0
      Behavior on opacity { NumberAnimation { duration: 100 } }
    }

    Rectangle {
      visible: root.hairline
      anchors.bottom: parent.bottom
      width: parent.width
      height: 1
      color: Plugin.Tokens.rowLine
    }
  }

  Item {
    id: cellsArea
    width: parent.width
    height: root.rowHeight

    // Tree indent guides, 1 px at 6 px into each 18 px level, continuous across rows.
    Repeater {
      model: root.depth
      delegate: Rectangle {
        required property int index
        x: root.table.cellX(1) + index * root.indent + Style.space(6)
        width: 1
        height: cellsArea.height
        color: Util.alpha(Color.foreground, 0.24)
      }
    }

    CheckBox {
      id: checkBox
      visible: root.check !== ""
      x: root.table ? root.table.cellX(0) : 0
      anchors.verticalCenter: parent.verticalCenter
      mark: root.check || "off"
      label: root.checkLabel
      onToggled: root.toggled()
    }

    Column {
      id: folder
      x: root.table ? root.table.cellX(1) + root.depth * root.indent : 0
      width: root.table ? root.table.widths[1] - root.depth * root.indent : 0
      anchors.verticalCenter: parent.verticalCenter
      spacing: root.pathGap

      Row {
        width: parent.width
        spacing: root.twisty !== "none" ? Style.space(6) : Style.space(8)

        Item {
          visible: root.twisty !== "none"
          width: Style.space(12)
          height: Style.space(12)
          anchors.verticalCenter: parent.verticalCenter

          Icon {
            anchors.centerIn: parent
            visible: root.twisty === "open" || root.twisty === "closed"
            name: root.twisty === "open" ? "twistyOpen" : "twisty"
            size: Style.space(12)
            color: Plugin.Tokens.dim
          }

          MouseArea {
            anchors.fill: parent
            anchors.margins: -Style.space(6)
            enabled: root.twisty === "open" || root.twisty === "closed"
            cursorShape: Qt.PointingHandCursor
            onClicked: root.twistyClicked()
          }
        }

        Label {
          id: nameText
          anchors.verticalCenter: parent.verticalCenter
          width: Math.min(implicitWidth, folder.width - (tag.visible ? tag.width + Style.space(8) : 0)
            - (root.twisty !== "none" ? Style.space(18) : 0))
          elide: Text.ElideRight
          textFormat: Text.PlainText
          text: root.name
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }

        RuleTag {
          id: tag
          anchors.verticalCenter: parent.verticalCenter
          visible: root.rule !== ""
          rule: root.rule
        }
      }

      // Hidden without facts, so a one-line row centers its name on the counts.
      Row {
        visible: !!root.facts && root.facts.length > 0
        width: parent.width
        height: Math.max(facts.implicitHeight, Style.space(16))
        spacing: Style.space(6)
        clip: true

        Item {
          visible: root.twisty !== "none"
          width: Style.space(12)
          height: 1
        }

        SetupFacts {
          id: facts
          anchors.verticalCenter: parent.verticalCenter
          tokens: root.facts
          fontSize: Style.font.bodySmall
        }

      }
    }

    Repeater {
      model: 5

      delegate: Label {
        required property int index
        readonly property var cell: root.cells && root.cells[index] ? root.cells[index] : ({n: 0, cut: false})
        readonly property bool zero: root.dash || !cell.n
        visible: !!root.table
        x: root.table ? root.table.cellX(index + 2) : 0
        width: root.table ? root.table.widths[index + 2] : 0
        anchors.verticalCenter: parent.verticalCenter
        horizontalAlignment: Text.AlignRight
        textFormat: !zero && cell.cut ? Text.StyledText : Text.PlainText
        text: root.dash ? "–"
          : zero ? "0"
          : cell.cut ? "<font color=\"" + Color.urgent + "\">−</font>" + root.formatted(cell.n)
          : root.formatted(cell.n)
        color: zero ? Plugin.Tokens.dim : cell.cut ? Plugin.Tokens.fg2 : Color.foreground
        font.family: Style.font.family
        font.pixelSize: root.numSize
      }
    }

    Label {
      visible: !root.pending && !!root.table
      x: root.table ? root.table.cellX(7) : 0
      width: root.table ? root.table.widths[7] : 0
      anchors.verticalCenter: parent.verticalCenter
      horizontalAlignment: Text.AlignRight
      text: root.indexText
      textFormat: Text.PlainText
      color: Color.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }

    Spinner {
      visible: root.pending && !!root.table
      running: visible
      x: root.table ? root.table.cellX(7) + root.table.widths[7] - width : 0
      anchors.verticalCenter: parent.verticalCenter
    }

    Label {
      visible: !!root.table
      x: root.table ? root.table.cellX(8) : 0
      width: root.table ? root.table.widths[8] : 0
      anchors.verticalCenter: parent.verticalCenter
      horizontalAlignment: Text.AlignRight
      text: root.timeText
      textFormat: Text.PlainText
      color: Color.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }

    Rectangle {
      id: actionButton
      visible: root.action === "code"
      x: root.table ? root.table.cellX(9) : 0
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(28)
      height: width
      radius: Style.cornerRadius
      color: actionMouse.pressed ? Style.selectedFill : actionMouse.containsMouse ? Style.hoverFill : "transparent"
      border.width: activeFocus ? 1 : 0
      border.color: activeFocus ? Color.accent : Style.normalBorderColor
      activeFocusOnTab: visible
      Accessible.role: Accessible.Button
      Accessible.name: root.actionLabel
      Behavior on color { ColorAnimation { duration: 100 } }

      Keys.onPressed: event => {
        if (event.key === Qt.Key_Space || event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
          root.actionClicked()
          event.accepted = true
        }
      }

      Icon {
        anchors.centerIn: parent
        name: "code"
        size: Style.space(12)
        color: root.actionActive ? Color.accent : Plugin.Tokens.dim
        Behavior on color { ColorAnimation { duration: 100 } }
      }

      MouseArea {
        id: actionMouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
          actionButton.forceActiveFocus()
          root.actionClicked()
        }
      }
    }

  }
}
