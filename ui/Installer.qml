pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Wayland
import "../lib/installer.js" as Install

// Runs package installs in Omarchy's floating terminal. `aside` asks the overlay to unmap until
// that terminal closes, since a normal window cannot stack above the overlay.
QtObject {
  id: root

  readonly property string appId: "org.omarchy.terminal"
  property var state: Install.initial()
  readonly property bool aside: state.aside

  function terminals() {
    var count = 0
    var values = ToplevelManager.toplevels.values
    for (var i = 0; i < values.length; i++)
      if (values[i] && values[i].appId === appId) count++
    return count
  }

  function reduce(event) { state = Install.reduce(state, event) }

  function install(packages) {
    reduce({type: "launch", terminals: terminals()})
    launchTimeout.restart()
    Quickshell.execDetached(["omarchy-launch-floating-terminal-with-presentation", "omarchy-pkg-add"]
      .concat(packages))
  }

  function end() {
    launchTimeout.stop()
    reduce({type: "end"})
  }

  property Connections toplevels: Connections {
    target: ToplevelManager.toplevels
    function onValuesChanged() { root.reduce({type: "terminals", terminals: root.terminals()}) }
  }

  property Timer launchTimeout: Timer {
    interval: 10000
    onTriggered: root.reduce({type: "timeout"})
  }
}
