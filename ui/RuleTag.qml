import QtQuick
import qs.Commons
import "." as Plugin

// `.tg`: 16 px rule tag. repo and user accent, worktree cyan, dataset yellow, secrets green with a lock, other rules dim.
Rectangle {
  id: root

  property string rule: ""

  readonly property color tone: rule === "user" || rule === "repo" ? Color.accent
    : rule === "worktree" ? Plugin.Palette.cyan
    : (rule === "generated" || rule === "dataset") ? Plugin.Palette.yellow
    : rule === "secrets" ? Plugin.Palette.green
    : Plugin.Tokens.dim

  implicitWidth: row.implicitWidth + 2 * Style.space(5)
  implicitHeight: Style.space(16)
  color: "transparent"
  border.width: 1
  border.color: rule === "user" || rule === "repo" ? Util.alpha(Color.accent, 0.5)
    : rule === "worktree" ? Util.alpha(Plugin.Palette.cyan, 0.42)
    : (rule === "generated" || rule === "dataset") ? Util.alpha(Plugin.Palette.yellow, 0.42)
    : rule === "secrets" ? Util.alpha(Plugin.Palette.green, 0.42)
    : Plugin.Tokens.sep

  Row {
    id: row
    anchors.centerIn: parent
    spacing: Style.space(4)

    Icon {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.rule === "secrets"
      name: "lock"
      size: Style.space(9)
      color: root.tone
    }

    Label {
      anchors.verticalCenter: parent.verticalCenter
      text: root.rule
      textFormat: Text.PlainText
      color: root.tone
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
      font.capitalization: Font.AllUppercase
      font.letterSpacing: Math.round(Style.font.bodySmall * Plugin.Tokens.tracking)
    }
  }
}
