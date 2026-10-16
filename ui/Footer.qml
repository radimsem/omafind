import QtQuick
import qs.Commons
import "." as Plugin
import "../lib/format.js" as Format

// `.sp-f`: the count on the left and the keys for the selection on the right.
// With no query it shows the index facts and indexing progress instead. `indexed` adds the
// `indexed` fact after the count, and `reconcile` ({text, fraction}) cross-fades over the left side.
Item {
  id: root

  signal progressClicked()

  property string text: ""
  // Labels of offline drives, shown in yellow after `text` while idle.
  property var offline: []
  property var hints: []
  property var progress: null
  // Indexed file count; -1 hides the token. It flashes in the accent when it grows (M4).
  property int indexed: -1
  property var reconcile: null
  property bool hot: false
  property int lastIndexed: -1
  // The last reconcile line stays drawn while it fades out.
  property var shownReconcile: null

  onReconcileChanged: if (reconcile) shownReconcile = reconcile

  onIndexedChanged: {
    if (lastIndexed >= 0 && indexed > lastIndexed) {
      hot = true
      cool.restart()
    }
    lastIndexed = indexed
  }

  implicitHeight: Plugin.Tokens.footerHeight

  Timer {
    id: cool
    interval: 900
    onTriggered: root.hot = false
  }

  Rectangle {
    anchors.top: parent.top
    width: parent.width
    height: 1
    color: Plugin.Tokens.sep
  }

  Item {
    id: left
    anchors.left: parent.left
    anchors.leftMargin: Style.space(18)
    anchors.right: right.left
    anchors.rightMargin: Style.space(16)
    anchors.top: parent.top
    anchors.bottom: parent.bottom

    Row {
      anchors.verticalCenter: parent.verticalCenter
      width: parent.width
      spacing: Style.space(8)
      opacity: root.reconcile ? 0 : 1
      Behavior on opacity { NumberAnimation { duration: 200 } }

      Label {
        anchors.verticalCenter: parent.verticalCenter
        width: Math.min(implicitWidth, parent.width - (indexedRow.visible ? indexedRow.width + parent.spacing : 0))
        elide: Text.ElideRight
        textFormat: Text.StyledText
        text: {
          var out = root.text.replace(/&/g, "&amp;").replace(/</g, "&lt;")
          for (var i = 0; i < root.offline.length; i++)
            out += " · <font color=\"" + Plugin.Palette.yellow + "\">"
              + String(root.offline[i]).replace(/&/g, "&amp;").replace(/</g, "&lt;") + " offline</font>"
          return out
        }
        color: Plugin.Tokens.dim
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }

      Row {
        id: indexedRow
        visible: root.indexed >= 0 && root.text !== ""
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(8)

        Label {
          anchors.verticalCenter: parent.verticalCenter
          text: "·"
          textFormat: Text.PlainText
          color: Plugin.Tokens.dim
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
        }

        Row {
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(5)

          Label {
            text: "indexed"
            textFormat: Text.PlainText
            color: Plugin.Tokens.dim
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
          }

          Label {
            objectName: "omafindIndexed"
            text: Format.count(Math.max(0, root.indexed))
            textFormat: Text.PlainText
            color: root.hot ? Color.accent : Plugin.Tokens.dim
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            transform: Translate {
              y: root.hot ? -2 : 0
              Behavior on y { NumberAnimation { duration: root.hot ? 80 : 400 } }
            }
            Behavior on color { ColorAnimation { duration: root.hot ? 80 : 700 } }
          }
        }
      }
    }

    Row {
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(8)
      opacity: root.reconcile ? 1 : 0
      visible: opacity > 0
      Behavior on opacity { NumberAnimation { duration: 200 } }

      Label {
        anchors.verticalCenter: parent.verticalCenter
        text: root.shownReconcile ? root.shownReconcile.text : ""
        textFormat: Text.PlainText
        color: Plugin.Tokens.dim
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }

      Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        width: Style.space(120)
        height: Style.space(4)
        color: Style.hoverFill
        clip: true

        Rectangle {
          height: parent.height
          width: parent.width * (root.shownReconcile ? Math.max(0, Math.min(1, root.shownReconcile.fraction)) : 0)
          color: Color.accent
          Behavior on width { NumberAnimation { duration: 300; easing.type: Easing.Linear } }
        }
      }
    }
  }

  Row {
    id: right
    anchors.right: parent.right
    anchors.rightMargin: Style.space(18)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(16)

    Row {
      id: progressRow
      visible: !!root.progress
      spacing: Style.space(6)
      anchors.verticalCenter: parent.verticalCenter

      Label {
        anchors.verticalCenter: parent.verticalCenter
        text: root.progress ? root.progress.text : ""
        textFormat: Text.PlainText
        color: Plugin.Tokens.dim
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }

      Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        width: Style.space(120)
        height: Style.space(4)
        color: Style.hoverFill
        clip: true

        Rectangle {
          height: parent.height
          width: parent.width * (root.progress ? Math.max(0, Math.min(1, root.progress.fraction)) : 0)
          color: Color.accent
          Behavior on width { NumberAnimation { duration: 300; easing.type: Easing.Linear } }
        }
      }
    }

    Repeater {
      model: root.hints

      delegate: Row {
        required property var modelData
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(6)

        Row {
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(4)
          Repeater {
            model: modelData.keys
            delegate: KeyCap {
              required property var modelData
              text: modelData
            }
          }
        }

        Label {
          anchors.verticalCenter: parent.verticalCenter
          text: modelData.label
          textFormat: Text.PlainText
          color: Plugin.Tokens.dim
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
        }
      }
    }
  }

  MouseArea {
    x: right.x + progressRow.x
    y: right.y + progressRow.y
    width: progressRow.width
    height: progressRow.height
    visible: progressRow.visible
    cursorShape: Qt.PointingHandCursor
    onClicked: root.progressClicked()
  }
}
