import QtQuick
import qs.Commons
import ".." as Plugin

// `.dt-r`: one folder table row, laid out on a FolderTable's columns. Serves the Discover rows,
// the left-out ledger entries and the Exclusions tree rows.
Item {
  id: root

  property var table: null
  // The folder this row stands for; the screenshot harness finds rows by it.
  property string path: ""
  property real rowHeight: Plugin.Tokens.tableRow
  // Check column: "on", "mixed", "off", or "" for an empty cell.
  property string check: ""
  property string checkLabel: ""
  // Ledger connector in the check column: "", "mid", "top" or "end".
  property string connector: ""
  property int depth: 0
  // "none" (no twisty column), "leaf" (its space only), "open" or "closed".
  property string twisty: "none"
  property string dirPrefix: ""
  property string name: ""
  property string rule: ""
  property var facts: []
  property bool showBar: false
  property var segments: []
  property real barWidth: Style.space(40)
  // Caret after the fact line of a root with a ledger: "", "open" or "closed".
  property string caret: ""
  property bool undo: false
  // Five kind cells: [{n, cut}] for numbers, or `dash` for repositories.
  property var cells: []
  property bool dash: false
  property real numSize: Style.font.body
  property string indexText: ""
  property string timeText: ""
  property bool hatched: false
  // Action column: "", "filter", "x" or "lock".
  property string action: ""
  property bool actionActive: false
  property string actionLabel: ""
  property string actionTitle: ""
  // Row fill: "", "on" (checked), "out" (left out), "hot" (restored just now), "added" (just left out).
  property string fill: ""
  property bool hairline: true
  // The secrets row of the tree: a dashed rule above and 6 px of air.
  property bool ruleTop: false
  property real pathGap: Style.space(2)

  signal toggled()
  signal actionClicked()
  signal twistyClicked()
  signal caretClicked()
  signal undoClicked()

  readonly property real topGap: ruleTop ? Style.space(6) : 0
  readonly property bool focused: check !== "" && checkBox.activeFocus
  readonly property bool out: fill === "out"
  readonly property real indent: Style.space(18)

  function focusCheck() {
    checkBox.forceActiveFocus()
  }

  function formatted(n) {
    return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",")
  }

  implicitHeight: rowHeight + topGap

  Rectangle {
    id: back
    y: root.topGap
    width: parent.width
    height: root.rowHeight
    color: root.fill === "on" ? Util.alpha(Color.accent, 0.06)
      : root.fill === "out" ? Plugin.Tokens.crust
      : root.fill === "hot" ? Util.alpha(Plugin.Palette.green, 0.06)
      : root.fill === "added" ? Util.alpha(Color.foreground, 0.05)
      : "transparent"
    Behavior on color { ColorAnimation { duration: 160 } }

    Rectangle {
      visible: root.fill === "hot"
      width: 2
      height: parent.height
      color: Plugin.Palette.green
    }

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

  Row {
    visible: root.ruleTop
    width: parent.width
    spacing: Style.space(3)
    Repeater {
      model: root.ruleTop ? Math.ceil(root.width / Style.space(6)) : 0
      delegate: Rectangle {
        width: Style.space(3)
        height: 1
        color: Util.alpha(Color.foreground, 0.16)
      }
    }
  }

  Item {
    id: cellsArea
    y: root.topGap
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

    // Ledger connector: a 1 px line at x 13 with a 13 px tick at mid height.
    Item {
      visible: root.connector !== ""
      x: root.table ? root.table.cellX(0) : 0
      width: Style.space(28)
      height: parent.height

      Rectangle {
        x: Style.space(13)
        width: 1
        height: root.connector === "end" ? parent.height / 2 : parent.height
        color: Util.alpha(Color.foreground, 0.32)
      }

      Rectangle {
        visible: root.connector !== "top"
        x: Style.space(13)
        y: Math.round(parent.height / 2)
        width: Style.space(13)
        height: 1
        color: Util.alpha(Color.foreground, 0.32)
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

        Text {
          id: nameText
          anchors.verticalCenter: parent.verticalCenter
          width: Math.min(implicitWidth, folder.width - (tag.visible ? tag.width + Style.space(8) : 0)
            - (root.twisty !== "none" ? Style.space(18) : 0))
          elide: Text.ElideRight
          textFormat: Text.StyledText
          text: (root.dirPrefix ? "<font color=\"" + Plugin.Tokens.dim + "\">" + root.dirPrefix.replace(/&/g, "&amp;").replace(/</g, "&lt;") + "</font>" : "")
            + root.name.replace(/&/g, "&amp;").replace(/</g, "&lt;")
          color: root.out ? Plugin.Tokens.fg2 : Color.foreground
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

      Row {
        width: parent.width
        height: Math.max(facts.implicitHeight, Style.space(16))
        spacing: Style.space(6)
        clip: true

        Item {
          visible: root.twisty !== "none"
          width: Style.space(12)
          height: 1
        }

        KindBar {
          anchors.verticalCenter: parent.verticalCenter
          visible: root.showBar
          segments: root.segments
          barWidth: root.barWidth
          opacity: root.out ? 0.45 : 1
        }

        SetupFacts {
          id: facts
          anchors.verticalCenter: parent.verticalCenter
          tokens: root.facts
          fontSize: Style.font.caption
        }

        // With the Row spacing on both sides this puts the caret 18 px after the facts.
        Item {
          visible: root.caret !== ""
          width: Style.space(6)
          height: 1
        }

        Icon {
          anchors.verticalCenter: parent.verticalCenter
          visible: root.caret !== ""
          name: root.caret === "open" ? "twistyOpen" : "twisty"
          size: Style.space(10)
          color: Plugin.Tokens.fg2

          MouseArea {
            anchors.fill: parent
            anchors.margins: -Style.space(6)
            cursorShape: Qt.PointingHandCursor
            onClicked: root.caretClicked()
          }
        }

        Text {
          anchors.verticalCenter: parent.verticalCenter
          visible: root.undo
          leftPadding: Style.space(6)
          text: "Undo"
          textFormat: Text.PlainText
          color: Color.accent
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          font.underline: true

          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: root.undoClicked()
          }
        }

        Row {
          anchors.verticalCenter: parent.verticalCenter
          visible: root.undo
          spacing: Style.space(6)
          SetupKey { text: "Ctrl"; fontSize: Plugin.Tokens.tiny; implicitHeight: Style.space(16); padding: Style.space(4) }
          SetupKey { text: "Z"; fontSize: Plugin.Tokens.tiny; implicitHeight: Style.space(16); padding: Style.space(4) }
        }
      }
    }

    Repeater {
      model: 5

      delegate: Text {
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

    Text {
      visible: !root.hatched && !!root.table
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

    Text {
      visible: !root.hatched && !!root.table
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

    Hatch {
      visible: root.hatched && !!root.table
      x: root.table ? root.table.cellX(7) + Style.space(18) : 0
      y: Style.space(8)
      width: root.table ? root.table.spanWidth(7, 2) - Style.space(18) : 0
      height: parent.height - 2 * Style.space(8)
      Accessible.name: "Not indexed"
    }

    Rectangle {
      id: actionButton
      visible: root.action === "filter" || root.action === "x"
      x: root.table ? root.table.cellX(9) : 0
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(28)
      height: width
      radius: Style.cornerRadius
      color: actionMouse.pressed ? Style.selectedFill : actionMouse.containsMouse ? Style.hoverFill : "transparent"
      border.width: root.fill === "added" || activeFocus ? 1 : 0
      border.color: activeFocus ? Color.accent : Style.normalBorderColor
      activeFocusOnTab: visible
      Accessible.role: Accessible.Button
      Accessible.name: root.actionLabel
      Accessible.description: root.actionTitle
      Behavior on color { ColorAnimation { duration: 100 } }

      Keys.onPressed: event => {
        if (event.key === Qt.Key_Space || event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
          root.actionClicked()
          event.accepted = true
        }
      }

      Icon {
        anchors.centerIn: parent
        name: root.action === "filter" ? "filter" : "x"
        size: Style.space(12)
        color: root.actionActive ? Color.accent
          : root.fill === "added" ? Color.foreground
          : root.out ? Plugin.Tokens.fg2
          : Plugin.Tokens.dim
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

    Item {
      visible: root.action === "lock"
      x: root.table ? root.table.cellX(9) : 0
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(28)
      height: width
      opacity: 0.75
      Accessible.name: "Always skipped"

      Icon {
        anchors.centerIn: parent
        name: "lock"
        size: Style.space(12)
        color: Plugin.Palette.green
      }
    }
  }
}
