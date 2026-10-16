pragma Singleton

import QtQuick
import Quickshell.Io
import qs.Commons

// Color exposes no green, yellow or cyan, so they come from the theme's colors.toml.
QtObject {
  id: root
  property var colors: ({})
  readonly property color green: colors.green || Color.foreground
  readonly property color yellow: colors.yellow || Color.urgent
  // The canvas defines no cyan fallback; the accent keeps images distinct from text.
  readonly property color cyan: colors.cyan || Color.accent

  property Connections themeChanges: Connections {
    target: Color
    // The shell replaces shellValues on every theme switch, even when the path stays the same.
    function onShellValuesChanged() { root.colorsFile.reload() }
  }

  property FileView colorsFile: FileView {
    path: Color.currentThemePath + "/colors.toml"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoadFailed: root.colors = {}
    onLoaded: {
      var values = {}
      var lines = text().split("\n")
      for (var i = 0; i < lines.length; i++) {
        var match = lines[i].match(/^\s*(green|yellow|cyan)\s*=\s*["']?(#[0-9a-fA-F]{6})/)
        if (match) values[match[1]] = match[2]
      }
      root.colors = values
    }
  }
}
