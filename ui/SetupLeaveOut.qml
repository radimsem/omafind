import QtQuick
import qs.Commons
import ".." as Plugin
import "../lib/setup.js" as Setup
import "../lib/ledger.js" as Ledger
import "../lib/tree.js" as Tree

// Board Exclusions (11b, M3 step 3): leave out subfolders of one root on a draft.
// "Done" hands the draft excludes and chosen folders back, "Cancel" and Esc drop them, Ctrl Z undoes one change.
FocusScope {
  id: root

  property var service: null
  property string rootPath: ""
  property var initialExcludes: []
  property var initialChosen: []
  property string home: ""
  property var rates: null
  property string device: "gpu"
  property string stepText: ""

  property var draft: null
  property real openedAt: Date.now()

  signal done(var excludes, var chosen)
  signal cancelled()

  readonly property var tree: service && service.trees ? service.trees[rootPath] || null : null
  readonly property var candidate: tree ? tree.candidate : null
  readonly property string shown: Setup.displayPath(rootPath, home)
  readonly property var ledger: tree && draft ? Tree.ledger(tree, draft.excludes, draft.chosen, Ledger.compute) : null
  readonly property var rows: tree && draft ? Tree.rows(tree, draft) : []
  readonly property var counts: tree && draft ? Tree.ruleCounts(tree, draft.excludes) : ({})
  readonly property int dirCount: candidate ? candidate.dirs : 0

  function focusFirst() {
    var first = list.itemAtIndex(0)
    if (first) first.focusCheck()
    else filterInput.forceActiveFocus()
  }

  function begin() {
    if (!tree || draft) return
    draft = Tree.initial(tree, initialExcludes, initialChosen)
    syncRows()
    Qt.callLater(focusFirst)
  }

  function now() {
    return Date.now()
  }

  function toggle(path) { if (draft) draft = Tree.toggle(draft, path, now()) }
  function expand(path, open) { if (draft) draft = Tree.expand(draft, path, open) }
  function selectByRule(rule) { if (draft) draft = Tree.selectByRule(draft, rule, now()) }
  function undo() { if (draft && draft.history.length) draft = Tree.undo(draft) }
  function setFilter(text) { if (draft) draft = Tree.setFilter(draft, text) }

  // "0.8 s ago" under 10 s, then the rough durations of lib/setup.js treeTime.
  function age() {
    if (!tree || !tree.scanned_at) return ""
    var seconds = Math.max(0, openedAt / 1000 - tree.scanned_at)
    return (seconds < 10 ? seconds.toFixed(1) + " s" : Setup.treeTime(seconds)) + " ago"
  }

  // The list keeps one delegate per path, so rows move and fade instead of being rebuilt.
  function syncRows() {
    var next = rows
    for (var i = 0; i < next.length; i++) {
      var json = JSON.stringify(next[i])
      if (i < rowModel.count && rowModel.get(i).path === next[i].path) {
        if (rowModel.get(i).json !== json) rowModel.setProperty(i, "json", json)
        continue
      }
      var found = -1
      for (var j = i + 1; j < rowModel.count; j++) if (rowModel.get(j).path === next[i].path) { found = j; break }
      if (found >= 0) {
        rowModel.move(found, i, 1)
        rowModel.setProperty(i, "json", json)
      } else {
        rowModel.insert(i, {path: next[i].path, json: json})
      }
    }
    if (rowModel.count > next.length) rowModel.remove(next.length, rowModel.count - next.length)
  }

  onTreeChanged: begin()
  onRowsChanged: if (draft) syncRows()
  Component.onCompleted: begin()

  ListModel { id: rowModel }

  component RuleChip: Rectangle {
    id: chip
    property string label: ""
    property int count: 0
    signal picked()
    enabled: count > 0
    opacity: enabled ? 1 : 0.5
    implicitWidth: chipRow.implicitWidth + 2 * Style.space(10)
    implicitHeight: Style.space(26)
    radius: Style.cornerRadius
    color: chipMouse.containsMouse && enabled ? Style.hoverFill : "transparent"
    border.width: 1
    border.color: activeFocus ? Color.accent : Plugin.Tokens.sep
    activeFocusOnTab: enabled
    Accessible.role: Accessible.Button
    Accessible.name: label
    Keys.onPressed: event => {
      if (event.key === Qt.Key_Space || event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
        chip.picked()
        event.accepted = true
      }
    }

    Row {
      id: chipRow
      anchors.centerIn: parent
      spacing: Style.space(8)
      Text {
        text: chip.label
        textFormat: Text.PlainText
        color: Plugin.Tokens.fg2
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }
      Text {
        text: String(chip.count)
        textFormat: Text.PlainText
        color: Plugin.Tokens.dim
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }
    }

    MouseArea {
      id: chipMouse
      anchors.fill: parent
      hoverEnabled: true
      enabled: chip.enabled
      cursorShape: Qt.PointingHandCursor
      onClicked: chip.picked()
    }
  }

  Column {
    id: top
    width: parent.width
    spacing: Plugin.Tokens.setupGap

    SetupHeader {
      width: parent.width
      crumb: "Folders"
      crumbLeaf: root.shown
      title: "Leave out parts of " + root.shown
      stepText: root.stepText
      facts: [
        {k: "source", v: "setup scan, " + root.age(), tone: "plain"},
        {k: "dirs", v: Setup.count(root.dirCount), tone: "plain"},
        {k: "files", v: Setup.count(root.ledger ? root.ledger.found.total : root.candidate ? root.candidate.found : 0), tone: "plain"},
        {k: "deletes", v: "nothing", tone: "plain"}
      ]
    }

    Item {
      width: parent.width
      height: Style.space(30)

      Row {
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(8)

        Rectangle {
          width: Style.space(260)
          height: Style.space(30)
          color: "transparent"
          border.width: 1
          border.color: filterInput.activeFocus ? Color.accent : Plugin.Tokens.sep

          Icon {
            id: searchIcon
            anchors.left: parent.left
            anchors.leftMargin: Style.space(10)
            anchors.verticalCenter: parent.verticalCenter
            name: "search"
            size: Style.space(14)
            color: Plugin.Tokens.dim
          }

          TextInput {
            id: filterInput
            anchors.left: searchIcon.right
            anchors.leftMargin: Style.space(8)
            anchors.right: parent.right
            anchors.rightMargin: Style.space(10)
            anchors.verticalCenter: parent.verticalCenter
            clip: true
            color: Color.foreground
            selectionColor: Util.alpha(Color.accent, 0.35)
            selectedTextColor: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            activeFocusOnTab: true
            Accessible.name: "Filter folders"
            onTextChanged: root.setFilter(text)
            Keys.priority: Keys.BeforeItem
            Keys.onPressed: event => {
              // Ctrl Z belongs to the tree, not to the field's own text undo.
              if (event.key === Qt.Key_Z && (event.modifiers & Qt.ControlModifier)) {
                root.undo()
                event.accepted = true
              }
            }

            Text {
              anchors.verticalCenter: parent.verticalCenter
              visible: filterInput.text === ""
              text: "Filter " + Setup.count(root.dirCount) + " folders"
              textFormat: Text.PlainText
              color: Plugin.Tokens.placeholder
              font: filterInput.font
            }
          }
        }

        Text {
          anchors.verticalCenter: parent.verticalCenter
          leftPadding: Style.space(10)
          text: "Select by rule"
          textFormat: Text.PlainText
          color: Plugin.Tokens.dim
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          font.capitalization: Font.AllUppercase
          font.letterSpacing: Style.font.caption * Plugin.Tokens.tracking
        }

        RuleChip {
          anchors.verticalCenter: parent.verticalCenter
          label: "no-kind"
          count: root.counts["no-kind"] || 0
          onPicked: root.selectByRule("no-kind")
        }

        RuleChip {
          anchors.verticalCenter: parent.verticalCenter
          label: "generated"
          count: root.counts.generated || 0
          onPicked: root.selectByRule("generated")
        }

        RuleChip {
          anchors.verticalCenter: parent.verticalCenter
          label: "files > 1,000"
          count: root.counts.big || 0
          onPicked: root.selectByRule("big")
        }
      }

      Row {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(8)

        KindBar {
          anchors.verticalCenter: parent.verticalCenter
          barWidth: Style.space(40)
          segments: [{kind: "text", n: 1}, {kind: "pdf", n: 1}, {kind: "image", n: 1}, {kind: "video", n: 1}, {kind: "audio", n: 1}]
        }

        Text {
          anchors.verticalCenter: parent.verticalCenter
          text: "files by kind"
          textFormat: Text.PlainText
          color: Plugin.Tokens.dim
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Hatch {
          anchors.verticalCenter: parent.verticalCenter
          width: Style.space(24)
          height: Style.space(10)
          spacing: 4
          alpha: 0.3
        }

        Text {
          anchors.verticalCenter: parent.verticalCenter
          text: "not indexed"
          textFormat: Text.PlainText
          color: Plugin.Tokens.dim
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }
      }
    }

    FolderTable {
      id: treeHeader
      width: parent.width
      kindDots: true
    }
  }

  Spinner {
    anchors.centerIn: list
    visible: !root.tree
    running: visible
  }

  ListView {
    id: list
    anchors.top: top.bottom
    anchors.bottom: bottomBar.top
    anchors.bottomMargin: Plugin.Tokens.setupGap
    width: parent.width
    clip: true
    model: rowModel
    boundsBehavior: Flickable.StopAtBounds
    keyNavigationEnabled: false

    add: Transition {
      NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 220; easing.type: Easing.BezierSpline; easing.bezierCurve: Plugin.Tokens.ease }
    }
    remove: Transition {
      NumberAnimation { property: "opacity"; to: 0; duration: 160 }
    }
    displaced: Transition {
      NumberAnimation { property: "y"; duration: 220; easing.type: Easing.BezierSpline; easing.bezierCurve: Plugin.Tokens.ease }
    }
    move: Transition {
      NumberAnimation { property: "y"; duration: 220; easing.type: Easing.BezierSpline; easing.bezierCurve: Plugin.Tokens.ease }
    }

    delegate: FolderRow {
      id: treeRow
      required property string json
      readonly property var r: JSON.parse(json)
      readonly property var estimate: Setup.estimate(r.counts, root.rates, root.device)
      objectName: "omafindTreeRow"
      width: list.width
      table: treeHeader
      path: r.path
      rowHeight: Plugin.Tokens.treeRow
      pathGap: Style.space(5)
      check: r.mark
      checkLabel: r.out ? "Keep " + r.name : r.mark === "mixed" ? "Keep all of " + r.name : "Keep " + r.name
      depth: r.depth
      twisty: r.expandable ? (r.expanded ? "open" : "closed") : "leaf"
      name: r.name
      rule: r.out && r.rule ? r.rule : ""
      facts: r.facts
      showBar: true
      segments: r.segments
      barWidth: Style.space(r.barWidth)
      undo: r.hot
      cells: Setup.KINDS.map(k => ({n: r.counts[k] || 0, cut: r.out}))
      hatched: r.out
      indexText: Setup.mb(estimate.bytes)
      timeText: Setup.treeTime(estimate.seconds)
      action: r.out ? "x" : ""
      actionLabel: "Keep " + r.name + " again"
      actionTitle: "Keep again"
      fill: r.out ? "out" : r.hot ? "hot" : ""
      onToggled: root.toggle(r.path)
      onActionClicked: root.toggle(r.path)
      onTwistyClicked: root.expand(r.path, !r.expanded)
      onUndoClicked: root.undo()
    }

    footer: FolderRow {
      readonly property var secrets: root.ledger ? root.ledger.secrets : null
      visible: !!secrets && secrets.files > 0
      width: list.width
      height: visible ? implicitHeight : 0
      table: treeHeader
      path: "**"
      rowHeight: Plugin.Tokens.treeRow
      pathGap: Style.space(5)
      ruleTop: true
      name: "**"
      rule: "secrets"
      facts: secrets ? Ledger.entryFacts({path: "**", rule: "secrets", counts: secrets.counts, files: secrets.files, evidence: secrets.evidence}) : []
      cells: Setup.KINDS.map(k => ({n: secrets ? secrets.counts[k] || 0 : 0, cut: true}))
      hatched: true
      action: "lock"
      fill: "out"
    }
  }

  Column {
    id: bottomBar
    anchors.bottom: parent.bottom
    width: parent.width
    spacing: Plugin.Tokens.setupGap

    Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }

    Item {
      width: parent.width
      height: Math.max(ledgerFooter.implicitHeight, Style.space(32))

      LedgerFooter {
        id: ledgerFooter
        anchors.verticalCenter: parent.verticalCenter
        footer: root.ledger && root.rates ? Ledger.footer(root.ledger, root.rates, root.device, root.rootPath, root.home) : null
      }

      Row {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(8)

        ActionButton {
          objectName: "omafindTreeCancel"
          text: "Cancel"
          focusable: true
          onClicked: root.cancelled()
        }

        ActionButton {
          objectName: "omafindTreeDone"
          text: "Done"
          primary: true
          neutral: true
          focusable: true
          enabled: !!root.draft
          onClicked: root.done(root.draft.excludes, root.draft.chosen)
        }
      }
    }
  }
}
