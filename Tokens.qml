pragma Singleton

import QtQuick
import qs.Commons

// Canvas tokens derived from the shell theme, and the sizes that have no Style token.
QtObject {
  readonly property color fg2: Util.alpha(Color.foreground, 0.85)
  readonly property color dim: Util.alpha(Color.foreground, 0.66)
  readonly property color placeholder: Util.alpha(Color.foreground, 0.55)
  readonly property color sep: Util.alpha(Color.foreground, 0.12)
  // Mocha surface0 over the overlay fill; checked by screenshot, not by a theme key.
  readonly property color surface0: Util.alpha(Color.foreground, 0.11)
  readonly property color well: Color.menu.background
  readonly property color chip: Util.alpha(Color.background, 0.85)
  readonly property color selectedRow: Util.alpha(Color.accent, 0.22)

  readonly property int overlayWidth: Style.space(1280)
  readonly property int overlayHeight: Style.space(800)
  // The overlay sits this far below the monitor centre, under the 26 px bar.
  readonly property int overlayOffset: Style.space(13)
  readonly property int queryHeight: Style.space(68)
  readonly property int listWidth: Style.space(470)
  readonly property int rowHeight: Style.space(56)
  readonly property int rowGap: Style.space(2)
  readonly property int headerHeight: Style.space(30)
  readonly property int weakHeight: Style.space(36)
  readonly property int footerHeight: Style.space(40)
  readonly property int mediaHeight: Style.space(420)

  // cubic-bezier(0.33, 1, 0.68, 1), the canvas easing.
  readonly property var ease: [0.33, 1, 0.68, 1, 1, 1]
}
