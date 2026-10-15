import QtQuick
import Quickshell
import qs.Commons
import ".." as Plugin
import "../lib/format.js" as Format

// `.it`: thumbnail or kind icon, name, folder or keyword snippet, and the jump badge.
Rectangle {
  id: root

  property var row: null
  property bool selected: false
  // A file that landed while the list was open (M4) wears the `new` badge for 2.8 s.
  property bool fresh: false

  signal clicked()

  readonly property var item: row && row.item ? row.item : ({})
  readonly property bool offline: item.offline === true
  readonly property bool weak: !!(row && row.weak)
  readonly property bool newBadge: fresh && !offline
  readonly property string badgeLabel: newBadge ? "new" : row && row.badge ? row.badge : ""
  // The label stays drawn while the badge fades out.
  property string shownBadge: ""
  onBadgeLabelChanged: if (badgeLabel) shownBadge = badgeLabel
  // A keyword hit shows its snippet in place of the folder.
  readonly property bool hasSnippet: {
    if (item.leg !== "words") return false
    var runs = item.snippet || []
    for (var i = 0; i < runs.length; i++) if (runs[i].m) return true
    return false
  }
  readonly property string thumbSource: item.thumb ? Util.fileUrl(item.thumb)
    : item.kind === "image" && !offline && item.path ? Util.fileUrl(item.path) : ""

  // A drive result reads `Label · /path`, online or offline; a home path reads `~/path`.
  function folder(entry) {
    var dir = entry.dir || ""
    var home = Quickshell.env("HOME") || ""
    if ((entry.offline || entry.drive) && entry.label) return entry.label + " · " + dir
    if (home && (dir === home || dir.indexOf(home + "/") === 0)) return "~" + dir.slice(home.length)
    return dir
  }

  function escaped(value) {
    return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  }

  function snippetMarkup(entry) {
    var runs = Format.snippetRuns(entry.snippet || [])
    var out = ""
    for (var i = 0; i < runs.length; i++) {
      out += runs[i].m ? "<b><font color=\"" + Color.foreground + "\">" + escaped(runs[i].t) + "</font></b>"
        : escaped(runs[i].t)
    }
    return out
  }

  implicitHeight: Plugin.Tokens.rowHeight
  radius: Style.cornerRadius
  color: selected ? Plugin.Tokens.selectedRow : "transparent"
  border.width: selected ? 1 : 0
  border.color: Color.accent

  Behavior on color { ColorAnimation { duration: 100 } }

  Rectangle {
    id: thumb
    anchors.left: parent.left
    anchors.leftMargin: Style.space(10)
    anchors.verticalCenter: parent.verticalCenter
    width: Style.space(44)
    height: Style.space(44)
    radius: Style.cornerRadius
    color: Plugin.Tokens.surface0
    clip: true
    opacity: root.offline ? 0.7 : 1
    Behavior on opacity { NumberAnimation { duration: 240 } }

    Icon {
      anchors.centerIn: parent
      visible: image.status !== Image.Ready
      name: root.item.kind || "text"
      size: Style.space(18)
      strokeWidth: 1.4
      color: Plugin.Tokens.fg2
    }

    Image {
      id: image
      anchors.fill: parent
      source: root.thumbSource
      sourceSize.width: Style.space(88)
      sourceSize.height: Style.space(88)
      fillMode: Image.PreserveAspectCrop
      asynchronous: true
      cache: true
    }
  }

  Column {
    anchors.left: thumb.right
    anchors.leftMargin: Style.space(12)
    anchors.right: root.badgeLabel ? badge.left : parent.right
    anchors.rightMargin: Style.space(root.badgeLabel ? 12 : 10)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(4)

    Label {
      width: parent.width
      text: root.item.name || ""
      textFormat: Text.PlainText
      elide: Text.ElideRight
      color: Color.foreground
      opacity: root.offline ? 0.7 : root.weak ? 0.6 : 1
      Behavior on opacity { NumberAnimation { duration: 240 } }
      font.family: Style.font.family
      font.pixelSize: Style.font.subtitle
      font.bold: true
    }

    Label {
      width: parent.width
      text: root.hasSnippet ? root.snippetMarkup(root.item) : root.escaped(root.folder(root.item))
      textFormat: Text.StyledText
      elide: Text.ElideRight
      maximumLineCount: 1
      color: root.selected ? Plugin.Tokens.fg2 : Plugin.Tokens.dim
      opacity: root.weak ? 0.6 : 1
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }
  }

  Rectangle {
    id: badge
    anchors.right: parent.right
    anchors.rightMargin: Style.space(10)
    anchors.verticalCenter: parent.verticalCenter
    visible: opacity > 0
    opacity: root.badgeLabel ? 1 : 0
    width: badgeText.implicitWidth + 2 * Style.space(7)
    height: Style.space(20)
    radius: Style.cornerRadius
    color: root.offline ? Util.alpha(Plugin.Palette.yellow, 0.12)
      : root.newBadge ? Util.alpha(Color.accent, 0.16) : Style.hoverFill
    // M4: the `new` badge fades in over 700 ms; other badges change over 240 ms.
    Behavior on opacity { NumberAnimation { duration: root.newBadge ? 700 : 240 } }

    Label {
      id: badgeText
      anchors.centerIn: parent
      text: root.shownBadge
      textFormat: Text.PlainText
      color: root.offline ? Plugin.Palette.yellow : root.newBadge ? Color.accent : Color.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      font.bold: true
    }
  }

  MouseArea {
    anchors.fill: parent
    cursorShape: Qt.PointingHandCursor
    onClicked: root.clicked()
  }
}
