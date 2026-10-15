import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import qs.Commons
import ".." as Plugin

// `.ntf` drive toasts (boards NewDrive, MotionFresh): "New drive found" with its two buttons, and
// the disconnected and connected notices. Cards stack 8 px apart at the top right. The window only
// takes clicks on the cards, so it can stay mapped while the overlay is closed.
PanelWindow {
  id: root

  property var service: null

  readonly property var toasts: service ? service.volumes.toasts : []
  readonly property real gap: Style.space(8)

  function focusedScreen() {
    var name = Hyprland.focusedMonitor ? String(Hyprland.focusedMonitor.name) : ""
    var screens = Quickshell.screens
    for (var i = 0; i < screens.length; i++)
      if (screens[i].name === name) return screens[i]
    return screens.length ? screens[0] : null
  }

  // Cards are keyed by toast id, so a leaving card fades where it is while the rest close up.
  function sync() {
    var ids = toasts.map(toast => toast.id)
    for (var i = 0; i < cards.count; i++) {
      var card = cards.get(i)
      if (card.shown && ids.indexOf(card.id) < 0) cards.setProperty(i, "shown", false)
    }
    var known = []
    for (var j = 0; j < cards.count; j++) known.push(cards.get(j).id)
    var arrived = false
    for (var k = 0; k < toasts.length; k++) {
      var at = known.indexOf(toasts[k].id)
      if (at < 0) {
        cards.append({id: toasts[k].id, json: JSON.stringify(toasts[k]), shown: false, entered: false})
        arrived = true
      } else if (!cards.get(at).shown) {
        cards.setProperty(at, "shown", true)
      }
    }
    if (arrived) {
      if (!visible) screen = focusedScreen()
      visible = true
      Qt.callLater(enter)
    }
    prune.restart()
  }

  function enter() {
    for (var i = 0; i < cards.count; i++) {
      var card = cards.get(i)
      if (!card.entered) {
        cards.setProperty(i, "entered", true)
        cards.setProperty(i, "shown", true)
      }
    }
  }

  onToastsChanged: sync()

  visible: false
  color: "transparent"
  anchors.top: true
  anchors.right: true
  margins.top: Style.space(36)
  margins.right: Style.space(10)
  implicitWidth: Style.space(380)
  implicitHeight: Math.max(1, stack.height + Style.space(12))
  WlrLayershell.namespace: "omafind-drive"
  WlrLayershell.layer: WlrLayer.Overlay
  WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
  exclusionMode: ExclusionMode.Ignore
  mask: Region { item: stack }

  ListModel { id: cards }

  // Removes cards once their 180 ms leave has played, and unmaps an empty stack.
  Timer {
    id: prune
    interval: 200
    onTriggered: {
      for (var i = cards.count - 1; i >= 0; i--)
        if (!cards.get(i).shown && cards.get(i).entered) cards.remove(i)
      if (!cards.count) root.visible = false
    }
  }

  Item {
    id: stack
    width: parent.width
    height: {
      var h = 0
      for (var i = 0; i < repeater.count; i++) {
        var card = repeater.itemAt(i)
        if (card && card.opacity > 0) h = Math.max(h, card.stackY + card.height)
      }
      return h
    }

    Repeater {
      id: repeater
      model: cards

      delegate: Rectangle {
        id: card

        required property int index
        required property string json
        required property bool shown

        readonly property var toast: JSON.parse(json)
        readonly property bool prompt: toast.kind === "drive"
        // Each shown card sits under the shown cards above it.
        readonly property real stackY: {
          var y = 0
          for (var i = 0; i < index; i++) {
            var above = repeater.itemAt(i)
            if (above && above.shown) y += above.height + root.gap
          }
          return y
        }

        objectName: "omafindDriveToast"
        y: stackY
        width: parent.width
        height: column.implicitHeight + 2 * Style.space(12) + 4
        radius: Style.cornerRadius
        color: Color.notifications.background
        border.width: 2
        border.color: Color.accent
        opacity: shown ? 1 : 0
        enabled: shown
        transform: Translate {
          y: card.shown ? 0 : -Style.space(12)
          Behavior on y { NumberAnimation { duration: 180; easing.type: Easing.BezierSpline; easing.bezierCurve: Plugin.Tokens.ease } }
        }
        Behavior on y { NumberAnimation { duration: 180; easing.type: Easing.BezierSpline; easing.bezierCurve: Plugin.Tokens.ease } }
        Behavior on opacity { NumberAnimation { duration: 180 } }
        Accessible.role: Accessible.AlertMessage
        Accessible.name: toast.title

        Column {
          id: column
          x: Style.space(14) + 2
          y: Style.space(12) + 2
          width: parent.width - 2 * (Style.space(14) + 2)
          spacing: Style.space(10)

          Row {
            spacing: Style.space(8)

            Icon {
              anchors.verticalCenter: parent.verticalCenter
              name: "drivePlugged"
              size: Style.space(14)
              color: card.toast.kind === "gone" ? Plugin.Palette.yellow
                : card.toast.kind === "returned" ? Plugin.Palette.green
                : Color.notifications.text
            }

            Label {
              anchors.verticalCenter: parent.verticalCenter
              width: Math.min(implicitWidth, column.width - Style.space(22))
              elide: Text.ElideMiddle
              text: card.toast.title
              textFormat: Text.PlainText
              color: Color.notifications.text
              font.family: Style.font.family
              font.pixelSize: Style.font.body
              font.bold: true
            }
          }

          Label {
            width: parent.width
            wrapMode: Text.Wrap
            text: card.toast.body
            textFormat: Text.PlainText
            color: Plugin.Tokens.fg2
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            lineHeightMode: Text.FixedHeight
            lineHeight: Style.space(18)
          }

          Item {
            visible: card.prompt
            width: parent.width
            height: actions.height

            Row {
              id: actions
              anchors.right: parent.right
              spacing: Style.space(8)

              Repeater {
                model: card.toast.buttons || []

                delegate: ActionButton {
                  required property var modelData
                  objectName: modelData.choice === "scan" ? "omafindDriveScan" : "omafindDriveIgnore"
                  text: modelData.label
                  primary: modelData.choice === "scan"
                  neutral: true
                  buttonHeight: Style.space(28)
                  onClicked: if (root.service) root.service.decideDrive(card.toast.uuid, modelData.choice)
                }
              }
            }
          }
        }
      }
    }
  }
}
