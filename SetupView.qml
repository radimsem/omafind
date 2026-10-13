import QtQuick
import qs.Commons

// Placeholder until issue #5 builds the setup flow.
Item {
  id: root

  property var service: null

  signal closeRequested()

  function handleKey(event) {
    if (event.key === Qt.Key_Escape) {
      root.closeRequested()
      event.accepted = true
    }
  }

  function reset() {}

  Text {
    anchors.centerIn: parent
    text: "Set up omafind"
    textFormat: Text.PlainText
    color: Color.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.heading
    font.bold: true
  }
}
