import QtQuick
import QtQuick.Shapes

// Line icons from the canvas boards, drawn in their 24 px viewBox and scaled to `size`.
Item {
  id: root

  property string name: ""
  property color color: "transparent"
  property real size: 14
  property real strokeWidth: 1.6
  property bool filled: false

  readonly property string circle11: "M18 11a7 7 0 1 1-14 0a7 7 0 1 1 14 0"
  readonly property var paths: ({
    search: circle11 + "M20 20l-4-4",
    why: circle11 + "M20 20l-4-4M8 11h6M11 8v6",
    code: "M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16",
    image: "M3 4h18v16H3zM11 10a2 2 0 1 1-4 0a2 2 0 1 1 4 0M21 16l-5-5-9 9",
    video: "M2 5h15v14H2zM17 10l5-3v10l-5-3",
    audio: "M9 18V5l12-2v13M9 18a3 3 0 1 1-6 0a3 3 0 1 1 6 0M21 16a3 3 0 1 1-6 0a3 3 0 1 1 6 0",
    pdf: "M6 2h9l5 5v15H6zM15 2v5h5",
    text: "M6 2h9l5 5v15H6zM9 12h7M9 16h7M9 8h3",
    play: "M7 4l13 8-13 8z",
    pause: "M6 4h4v16H6zM14 4h4v16h-4z",
    chevron: "M9 6l6 6-6 6",
    warn: "M12 3l10 18H2zM12 10v5M12 18v.01",
    drive: "M3 6h18v12H3zM7 12h.01",
    check: "M5 12l5 5 9-10",
    x: "M6 6l12 12M18 6L6 18",
    lock: "M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4",
    plus: "M12 5v14M5 12h14",
    filter: "M4 6h16M7 12h10M10 18h4",
    twistyOpen: "M7 10l5 5 5-5",
    twisty: "M10 7l5 5-5 5",
    dash: "M6 12h12"
  })

  implicitWidth: size
  implicitHeight: size

  Shape {
    anchors.centerIn: parent
    width: 24
    height: 24
    scale: root.size / 24
    preferredRendererType: Shape.CurveRenderer

    ShapePath {
      strokeColor: root.filled ? "transparent" : root.color
      strokeWidth: root.filled ? 0 : root.strokeWidth
      fillColor: root.filled ? root.color : "transparent"
      capStyle: ShapePath.RoundCap
      joinStyle: ShapePath.RoundJoin
      PathSvg { path: root.paths[root.name] || "" }
    }
  }
}
