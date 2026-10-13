import QtQuick
import qs.Commons

// The one gradient: 1 px foreground lines at 135 degrees, `spacing` px apart, marking what is not indexed.
Canvas {
  id: root

  property real spacing: 6
  property real alpha: 0.16

  onSpacingChanged: requestPaint()
  onAlphaChanged: requestPaint()
  onWidthChanged: requestPaint()
  onHeightChanged: requestPaint()

  Connections {
    target: Color
    function onForegroundChanged() { root.requestPaint() }
  }

  onPaint: {
    var ctx = getContext("2d")
    ctx.reset()
    ctx.strokeStyle = Util.alpha(Color.foreground, root.alpha)
    ctx.lineWidth = 1
    // Lines x + y = c; their perpendicular distance is step / sqrt(2).
    var step = root.spacing * Math.SQRT2
    ctx.beginPath()
    for (var c = step / 2; c < width + height; c += step) {
      ctx.moveTo(c, 0)
      ctx.lineTo(c - height, height)
    }
    ctx.stroke()
  }
}
