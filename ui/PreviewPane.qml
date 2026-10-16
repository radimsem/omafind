import QtQuick

// `.sp-pv`: the selected result. Two layers cross-fade over 120 ms when the selection changes.
Item {
  id: root

  property var item: null
  property var preview: null
  property var player: null
  property var markers: []
  property string editorName: "Neovim"
  property string flash: ""
  readonly property var current: front ? first : second
  readonly property var videoOutput: current.item && current.item.kind === "video" ? current.videoOutput : null
  property bool front: true
  property bool pendingSwap: false

  signal primaryClicked()
  signal secondaryClicked()
  signal playClicked()

  function show(next) {
    gate.stop()
    pendingSwap = false
    var layer = current
    if (!next) {
      first.shown = false
      second.shown = false
      return
    }
    if (layer.item && layer.item.id === next.id) {
      layer.item = next
      layer.shown = true
      return
    }
    var incoming = front ? second : first
    incoming.preview = preview && preview.id === next.id ? preview : null
    incoming.item = next
    pendingSwap = true
    if (incoming.mediaReady) swap()
    else gate.restart()
  }

  // Swaps layers once the incoming one has its picture, or after 150 ms at the latest.
  function swap() {
    if (!pendingSwap) return
    pendingSwap = false
    gate.stop()
    var incoming = front ? second : first
    current.shown = false
    incoming.shown = true
    front = !front
  }

  Timer {
    id: gate
    interval: 150
    onTriggered: root.swap()
  }

  Connections {
    target: root.front ? second : first
    function onMediaReadyChanged() {
      if (gate.running && (root.front ? second : first).mediaReady) root.swap()
    }
  }

  onItemChanged: show(item)
  onPreviewChanged: {
    if (preview && current.item && preview.id === current.item.id) current.preview = preview
    var incoming = front ? second : first
    if (pendingSwap && preview && incoming.item && preview.id === incoming.item.id) incoming.preview = preview
  }

  PreviewLayer {
    id: first
    anchors.fill: parent
    player: root.player
    markers: root.current === first ? root.markers : []
    editorName: root.editorName
    flash: root.current === first ? root.flash : ""
    onPrimaryClicked: root.primaryClicked()
    onSecondaryClicked: root.secondaryClicked()
    onPlayClicked: root.playClicked()
  }

  PreviewLayer {
    id: second
    anchors.fill: parent
    player: root.player
    markers: root.current === second ? root.markers : []
    editorName: root.editorName
    flash: root.current === second ? root.flash : ""
    onPrimaryClicked: root.primaryClicked()
    onSecondaryClicked: root.secondaryClicked()
    onPlayClicked: root.playClicked()
  }
}
