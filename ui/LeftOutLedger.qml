import QtQuick
import QtQuick.Shapes
import qs.Commons
import ".." as Plugin
import "../lib/ledger.js" as Ledger

// `.lo`: what a root leaves out, nested under it on a crust wash and joined by a tree connector.
// Header with summed removed counts, one row per entry, then "Leave out a subfolder".
Item {
  id: root

  property var table: null
  // lib/ledger.js compute() shape: {leftOut, entries, ...}.
  property var ledger: null
  // "~/Documents/", drawn dim before each entry path.
  property string prefix: ""
  property string hotPath: ""
  property bool open: false

  signal includeAgain(string path)
  signal leaveOutRequested()

  readonly property var kinds: ["text", "pdf", "image", "video", "audio"]
  readonly property var entries: ledger && ledger.entries ? ledger.entries : []

  function cutCells(counts) {
    return kinds.map(k => ({n: counts ? counts[k] || 0 : 0, cut: true}))
  }

  implicitHeight: open ? body.implicitHeight : 0
  height: implicitHeight
  opacity: open ? 1 : 0
  clip: true
  Behavior on implicitHeight { NumberAnimation { duration: 240; easing.type: Easing.BezierSpline; easing.bezierCurve: Plugin.Tokens.ease } }
  Behavior on opacity { NumberAnimation { duration: 160 } }

  Rectangle {
    anchors.fill: body
    color: Plugin.Tokens.crust

    Rectangle {
      anchors.bottom: parent.bottom
      width: parent.width
      height: 1
      color: Plugin.Tokens.rowLine
    }
  }

  Column {
    id: body
    width: parent.width
    bottomPadding: Style.space(4)

    Item {
      id: head
      visible: root.entries.length > 0
      width: parent.width
      height: Plugin.Tokens.leftOutHead

      Item {
        x: root.table ? root.table.cellX(0) : 0
        width: Style.space(28)
        height: parent.height

        Rectangle {
          x: Style.space(13)
          width: 1
          height: parent.height
          color: Util.alpha(Color.foreground, 0.32)
        }
      }

      Row {
        x: root.table ? root.table.cellX(1) : 0
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(6)

        Text {
          text: "Left out"
          textFormat: Text.PlainText
          color: Plugin.Tokens.dim
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          font.capitalization: Font.AllUppercase
          font.letterSpacing: Style.font.caption * Plugin.Tokens.tracking
        }

        Text {
          text: root.ledger ? Ledger.header(root.ledger) : ""
          textFormat: Text.PlainText
          color: Plugin.Tokens.fg2
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          font.capitalization: Font.AllUppercase
        }
      }

      FolderRow {
        anchors.fill: parent
        table: root.table
        rowHeight: parent.height
        hairline: false
        cells: root.cutCells(root.ledger ? root.ledger.leftOut : null)
        numSize: Style.font.bodySmall
      }

      Item {
        id: notIndexed
        x: root.table ? root.table.cellX(7) + Style.space(18) : 0
        width: root.table ? root.table.spanWidth(7, 2) - Style.space(18) : 0
        height: parent.height

        Text {
          anchors.centerIn: parent
          text: "not indexed"
          textFormat: Text.PlainText
          color: Plugin.Tokens.dim
          font.family: Style.font.family
          font.pixelSize: Plugin.Tokens.tiny
          font.capitalization: Font.AllUppercase
          font.letterSpacing: Plugin.Tokens.tiny * Plugin.Tokens.tagTracking
        }

        Row {
          anchors.bottom: parent.bottom
          spacing: Style.space(3)
          Repeater {
            model: Math.ceil(notIndexed.width / Style.space(6))
            delegate: Rectangle {
              width: Style.space(3)
              height: 1
              color: Util.alpha(Color.foreground, 0.2)
            }
          }
        }
      }
    }

    Repeater {
      model: root.entries

      delegate: FolderRow {
        required property var modelData
        readonly property bool secrets: modelData.rule === "secrets"
        width: body.width
        table: root.table
        path: modelData.path
        rowHeight: Plugin.Tokens.leftOutRow
        hairline: false
        connector: "mid"
        pathGap: Style.space(6)
        dirPrefix: root.prefix
        name: modelData.path
        rule: modelData.rule
        facts: Ledger.entryFacts(modelData)
        cells: root.cutCells(modelData.counts)
        hatched: true
        action: secrets ? "lock" : "x"
        actionLabel: "Include " + modelData.path + " again"
        actionTitle: "Include again"
        fill: !secrets && modelData.path === root.hotPath ? "added" : ""
        onActionClicked: if (!secrets) root.includeAgain(modelData.path)
      }
    }

    Item {
      width: parent.width
      height: Style.space(34)

      Item {
        x: root.table ? root.table.cellX(0) : 0
        width: Style.space(28)
        height: parent.height

        Rectangle {
          x: Style.space(13)
          width: 1
          height: parent.height / 2
          color: Util.alpha(Color.foreground, 0.32)
        }

        Rectangle {
          x: Style.space(13)
          y: Math.round(parent.height / 2)
          width: Style.space(13)
          height: 1
          color: Util.alpha(Color.foreground, 0.32)
        }
      }

      // `.addx`: a dashed 24 px button.
      Item {
        id: addButton
        objectName: "omafindLeaveOut"
        x: root.table ? root.table.cellX(1) : 0
        anchors.verticalCenter: parent.verticalCenter
        width: addRow.implicitWidth + 2 * Style.space(10)
        height: Style.space(24)
        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: "Leave out a subfolder"

        Keys.onPressed: event => {
          if (event.key === Qt.Key_Space || event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
            root.leaveOutRequested()
            event.accepted = true
          }
        }

        Rectangle {
          anchors.fill: parent
          radius: Style.cornerRadius
          color: addMouse.containsMouse ? Style.hoverFill : "transparent"
        }

        Shape {
          anchors.fill: parent
          preferredRendererType: Shape.CurveRenderer

          ShapePath {
            strokeColor: addButton.activeFocus ? Color.accent : Style.normalBorderColor
            strokeWidth: 1
            strokeStyle: ShapePath.DashLine
            dashPattern: [3, 2]
            fillColor: "transparent"
            startX: 0.5; startY: 0.5
            PathLine { x: addButton.width - 0.5; y: 0.5 }
            PathLine { x: addButton.width - 0.5; y: addButton.height - 0.5 }
            PathLine { x: 0.5; y: addButton.height - 0.5 }
            PathLine { x: 0.5; y: 0.5 }
          }
        }

        Row {
          id: addRow
          anchors.centerIn: parent
          spacing: Style.space(8)

          Icon {
            anchors.verticalCenter: parent.verticalCenter
            name: "plus"
            size: Style.space(11)
            color: Plugin.Tokens.fg2
          }

          Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "Leave out a subfolder"
            textFormat: Text.PlainText
            color: Plugin.Tokens.fg2
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
          }
        }

        MouseArea {
          id: addMouse
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: {
            addButton.forceActiveFocus()
            root.leaveOutRequested()
          }
        }
      }
    }
  }
}
