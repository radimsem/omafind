import QtQuick
import QtQuick.Shapes
import qs.Commons

// The 12 px ring from the query row: a faint track and one accent quarter turning every 0.9 s.
Item {
  id: root

  property bool running: true

  implicitWidth: Style.space(12)
  implicitHeight: Style.space(12)

  Shape {
    id: ring
    anchors.fill: parent
    preferredRendererType: Shape.CurveRenderer
    readonly property real r: (width - 2) / 2

    ShapePath {
      strokeColor: Util.alpha(Color.accent, 0.25)
      strokeWidth: 2
      fillColor: "transparent"
      PathAngleArc {
        centerX: ring.width / 2
        centerY: ring.height / 2
        radiusX: ring.r
        radiusY: ring.r
        startAngle: 0
        sweepAngle: 360
      }
    }

    ShapePath {
      strokeColor: Color.accent
      strokeWidth: 2
      fillColor: "transparent"
      PathAngleArc {
        centerX: ring.width / 2
        centerY: ring.height / 2
        radiusX: ring.r
        radiusY: ring.r
        startAngle: -135
        sweepAngle: 90
      }
    }

    RotationAnimator on rotation {
      from: 0
      to: 360
      duration: 900
      loops: Animation.Infinite
      running: root.running && root.visible
    }
  }
}
