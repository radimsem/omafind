import QtQuick
import qs.Commons
import ".." as Plugin

// One flat, keyed model. A new result set moves existing rows to their new place instead of
// rebuilding them, so words-then-meaning re-ranks slide and the selection follows its row.
Item {
  id: root

  property var rows: []
  property int selectedIndex: -1
  readonly property string selectedKey: rows[selectedIndex] ? rows[selectedIndex].key : ""
  property var byKey: ({})
  property var indexByKey: ({})
  property real contentHeight: 0
  // Keys of files that landed while the list was open. Set before `rows` so they enter as fresh rows.
  property var freshKeys: []

  signal picked(int index)
  signal weakToggled(int index)

  function heightOf(row) {
    if (row.type === "header") return Plugin.Tokens.headerHeight
    if (row.type === "weak") return Plugin.Tokens.weakHeight + Plugin.Tokens.rowGap
    return Plugin.Tokens.rowHeight + Plugin.Tokens.rowGap
  }

  function sync() {
    var place = {}
    var rowsByKey = {}
    var indexes = {}
    // The first header's top padding overlaps the pane padding, as `.lst { margin-top: -8px }` does.
    var y = -Style.space(8)
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i]
      place[row.key] = y
      rowsByKey[row.key] = row
      indexes[row.key] = i
      y += heightOf(row)
    }
    contentHeight = Math.max(0, y)
    byKey = rowsByKey
    indexByKey = indexes

    var known = {}
    for (var j = slots.count - 1; j >= 0; j--) {
      var slot = slots.get(j)
      known[slot.key] = true
      if (place[slot.key] !== undefined) {
        slots.set(j, {ty: place[slot.key], shown: true, delay: 0, leaving: false, slow: false})
      } else if (!slot.leaving) {
        slots.set(j, {ty: slot.ty + Style.space(8), shown: false, delay: 0, leaving: true})
      }
    }
    var arriving = 0
    var appeared = false
    for (var k = 0; k < rows.length; k++) {
      var key = rows[k].key
      if (known[key]) continue
      // Rows that appear start 10 px above their place and stagger by 20 ms. A new file (M4)
      // slides 18 px over 240 ms.
      var landed = freshKeys.indexOf(key) >= 0
      slots.append({key: key, ty: place[key] - Style.space(landed ? 18 : 10), target: place[key], shown: false,
        delay: landed ? 0 : arriving * 20, leaving: false, fresh: true, slow: landed})
      if (!landed) arriving += 1
      appeared = true
    }
    if (appeared) Qt.callLater(reveal)
    if (rows.length !== slots.count) prune.restart()
    Qt.callLater(ensureVisible)
  }

  function reveal() {
    for (var i = 0; i < slots.count; i++) {
      var slot = slots.get(i)
      if (slot.fresh) slots.set(i, {ty: slot.target, shown: true, fresh: false})
    }
  }

  function ensureVisible() {
    var key = selectedKey
    for (var i = 0; i < slots.count; i++) {
      var slot = slots.get(i)
      if (slot.key !== key) continue
      var top = slot.fresh ? slot.target : slot.ty
      var bottom = top + heightOf(rows[selectedIndex] || {type: "item"})
      var target = flick.contentY
      if (top < flick.contentY) target = top
      else if (bottom > flick.contentY + flick.height) target = bottom - flick.height
      // The previous section header stays in view when the first row of a section is selected.
      var previous = rows[selectedIndex - 1]
      if (previous && previous.type === "header" && target === top) target -= Plugin.Tokens.headerHeight
      scroll.to = Math.max(0, Math.min(target, Math.max(0, contentHeight - flick.height)))
      if (Math.abs(scroll.to - flick.contentY) > 0.5) scroll.restart()
      return
    }
  }

  function reset() {
    slots.clear()
    flick.contentY = 0
  }

  onRowsChanged: sync()
  onSelectedIndexChanged: Qt.callLater(ensureVisible)

  ListModel { id: slots }

  Timer {
    id: prune
    interval: 260
    onTriggered: {
      for (var i = slots.count - 1; i >= 0; i--)
        if (slots.get(i).leaving) slots.remove(i)
    }
  }

  Flickable {
    id: flick
    anchors.fill: parent
    clip: true
    contentWidth: width
    contentHeight: root.contentHeight
    contentY: 0
    boundsBehavior: Flickable.StopAtBounds

    NumberAnimation {
      id: scroll
      target: flick
      property: "contentY"
      duration: 160
      easing.type: Easing.BezierSpline
      easing.bezierCurve: Plugin.Tokens.ease
    }

    Repeater {
      model: slots

      delegate: Item {
        id: slot

        required property string key
        required property real ty
        required property bool shown
        required property int delay
        required property bool slow

        readonly property var row: root.byKey[key] || null
        readonly property string type: row ? row.type : ""
        readonly property int rowIndex: root.indexByKey[key] !== undefined ? root.indexByKey[key] : -1

        width: flick.width
        height: type === "header" ? Plugin.Tokens.headerHeight
          : type === "weak" ? Plugin.Tokens.weakHeight : Plugin.Tokens.rowHeight
        y: ty
        opacity: shown ? 1 : 0

        Behavior on y {
          SequentialAnimation {
            PauseAnimation { duration: slot.delay }
            NumberAnimation { duration: slot.slow ? 240 : 220; easing.type: Easing.BezierSpline; easing.bezierCurve: Plugin.Tokens.ease }
          }
        }
        Behavior on opacity {
          SequentialAnimation {
            PauseAnimation { duration: slot.delay }
            NumberAnimation { duration: slot.slow ? 240 : 160 }
          }
        }

        SectionHeader {
          anchors.fill: parent
          visible: slot.type === "header"
          title: slot.row && slot.type === "header" ? slot.row.title : ""
          count: slot.row && slot.type === "header" ? slot.row.count : 0
        }

        ResultRow {
          anchors.fill: parent
          visible: slot.type === "item"
          row: slot.type === "item" ? slot.row : null
          selected: slot.key === root.selectedKey
          fresh: root.freshKeys.indexOf(slot.key) >= 0
          onClicked: root.picked(slot.rowIndex)
        }

        WeakRow {
          anchors.fill: parent
          visible: slot.type === "weak"
          count: slot.row && slot.type === "weak" ? slot.row.count : 0
          selected: slot.key === root.selectedKey
          expanded: slot.row && slot.type === "weak" ? !!slot.row.expanded : false
          onClicked: {
            root.picked(slot.rowIndex)
            root.weakToggled(slot.rowIndex)
          }
        }
      }
    }
  }
}
