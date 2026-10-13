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

  // Setup panel. The M3 panel sizes come unscaled from lib/setup.js panelSize.
  readonly property int setupPadding: Style.space(18)
  readonly property int setupGap: Style.space(14)
  readonly property int tableRow: Style.space(44)
  readonly property int leftOutRow: Style.space(50)
  readonly property int leftOutHead: Style.space(30)
  readonly property int treeRow: Style.space(46)
  readonly property int tableHeader: Style.space(30)
  readonly property int tableGap: Style.space(10)
  readonly property int tablePadding: Style.space(10)
  // `.dt` columns: check, folder (0 = flexible), text, pdf, images, video, audio, index, time, action.
  readonly property var tableColumns: [28, 0, 64, 56, 64, 56, 56, 84, 72, 32].map(px => Style.space(px))
  // The boards' 9 px (rule tags, key caps inside rows) has no Style.font token.
  readonly property int tiny: Math.round(Style.font.caption * 0.9)
  // Tracking of uppercase captions in em: headers 0.08, rule tags 0.06.
  readonly property real tracking: 0.08
  readonly property real tagTracking: 0.06
  readonly property color crust: Util.alpha(Color.background, 0.42)
  readonly property color rowLine: Util.alpha(Color.foreground, 0.06)

  // cubic-bezier(0.33, 1, 0.68, 1), the canvas easing.
  readonly property var ease: [0.33, 1, 0.68, 1, 1, 1]
}
