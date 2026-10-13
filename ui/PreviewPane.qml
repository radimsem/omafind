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

  signal primaryClicked()
  signal secondaryClicked()
  signal playClicked()

  function show(next) {
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
    layer.shown = false
    incoming.shown = true
    front = !front
  }

  onItemChanged: show(item)
  onPreviewChanged: {
    if (preview && current.item && preview.id === current.item.id) current.preview = preview
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
