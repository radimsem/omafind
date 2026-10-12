import QtQuick

Item {
  id: root

  property var shell: null
  property var manifest: null
  property bool opened: false
  property string payloadJson: ""

  function open(payload) {
    root.payloadJson = payload || ""
    root.opened = true
  }

  function close() {
    root.opened = false
  }
}
