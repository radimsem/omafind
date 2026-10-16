import QtQuick
import qs.Commons
import ".." as Plugin
import "../lib/errors.js" as Errors

// The "Add folder" picker inside the overlay (plan D11): a path field completed from `fs_list`.
// A portal or FolderDialog window would open beneath the exclusive-focus overlay layer.
// Tab completes the first match, Enter adds, Esc closes the field.
Item {
  id: root

  property var service: null

  signal added(string path)
  signal cancelled()

  property string asked: ""
  property var listing: null

  readonly property string value: input.text
  readonly property int slash: value.lastIndexOf("/")
  readonly property bool rooted: value.charAt(0) === "/" || value.charAt(0) === "~"
  // "~/Doc" lists "~" and matches "Doc"; "/" lists "/".
  readonly property string parentPath: !rooted ? "" : slash < 0 ? "" : slash === 0 ? "/" : value.slice(0, slash)
  readonly property string stem: slash < 0 ? "" : value.slice(slash + 1)
  readonly property var matches: {
    if (!listing || listing.path !== parentPath || !listing.dirs) return []
    var low = stem.toLowerCase()
    return listing.dirs.filter(name => name.toLowerCase().indexOf(low) === 0).slice(0, 6)
  }
  readonly property string error: listing && listing.path === parentPath && listing.error ? Errors.wrap(listing.error).title : ""

  function focusField() {
    input.forceActiveFocus()
  }

  function reset() {
    input.text = ""
    listing = null
    asked = ""
  }

  function complete(name) {
    input.text = (parentPath === "/" ? "" : parentPath) + "/" + name + "/"
    input.cursorPosition = input.text.length
  }

  function submit() {
    var path = value.trim().replace(/(.)\/+$/, "$1")
    if (path === "" || !rooted) return
    added(path)
  }

  onParentPathChanged: listTimer.restart()

  implicitHeight: column.implicitHeight

  Timer {
    id: listTimer
    interval: 80
    onTriggered: {
      if (root.parentPath === "" || root.parentPath === root.asked || !root.service) return
      root.asked = root.parentPath
      root.service.listDirs(root.parentPath)
    }
  }

  Connections {
    target: root.service
    ignoreUnknownSignals: true
    function onFsListReceived(reply) {
      if (reply && reply.path === root.asked) root.listing = reply
    }
  }

  Column {
    id: column
    width: parent.width
    spacing: Style.space(6)

    Row {
      spacing: Style.space(8)

      Rectangle {
        width: Style.space(360)
        height: Style.space(28)
        color: "transparent"
        border.width: 1
        border.color: input.activeFocus ? Color.accent : Plugin.Tokens.sep

        TextInput {
          id: input
          objectName: "omafindPathField"
          anchors.fill: parent
          anchors.leftMargin: Style.space(10)
          anchors.rightMargin: Style.space(10)
          verticalAlignment: TextInput.AlignVCenter
          clip: true
          color: Color.foreground
          selectionColor: Util.alpha(Color.accent, 0.35)
          selectedTextColor: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          selectByMouse: true
          activeFocusOnTab: true
          Keys.priority: Keys.BeforeItem
          Keys.onPressed: event => {
            if (event.key === Qt.Key_Tab && root.matches.length > 0) {
              root.complete(root.matches[0])
              event.accepted = true
            } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
              root.submit()
              event.accepted = true
            } else if (event.key === Qt.Key_Escape) {
              root.cancelled()
              event.accepted = true
            }
          }
        }

        Label {
          anchors.left: parent.left
          anchors.leftMargin: Style.space(10)
          anchors.verticalCenter: parent.verticalCenter
          visible: input.text === ""
          text: "Folder path"
          textFormat: Text.PlainText
          color: Plugin.Tokens.placeholder
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }
      }

      ActionButton {
        anchors.verticalCenter: parent.verticalCenter
        text: "Add"
        focusable: true
        buttonHeight: Style.space(28)
        enabled: root.rooted && root.error === ""
        onClicked: root.submit()
      }
    }

    Row {
      visible: root.matches.length > 0 || root.error !== ""
      spacing: Style.space(10)

      SetupFacts {
        visible: root.error !== ""
        tokens: [{k: "path", v: root.error, tone: "warn"}]
        fontSize: Style.font.bodySmall
      }

      Repeater {
        model: root.error === "" ? root.matches : []

        delegate: Label {
          required property string modelData
          required property int index
          text: modelData
          textFormat: Text.PlainText
          color: index === 0 ? Color.accent : Plugin.Tokens.fg2
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall

          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: {
              root.complete(parent.modelData)
              input.forceActiveFocus()
            }
          }
        }
      }
    }
  }
}
