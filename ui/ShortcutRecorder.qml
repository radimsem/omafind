import QtQuick
import Quickshell
import Quickshell.Io
import "../lib/keycombo.js" as Keycombo

// Ported from omaone/ui/settings/Shortcuts.qml; every enter must be followed by a leave.
Item {
  id: recorder
  visible: false

  property var binds: ({})
  readonly property bool active: recording
  property bool recording: false
  property string conflict: ""
  // Hyprland is outside the submap, so bound chords still fire.
  property bool exposed: false
  // Hyprland left the submap mid-recording.
  property bool lost: false
  property string nonce: ""
  property string operation: ""
  property bool pendingLeave: false
  property int leaveRetries: 0
  property string accepted: ""
  property string polledNonce: ""

  signal recorded(string chord)

  Component.onDestruction: {
    if (nonce !== "") Quickshell.execDetached(Keycombo.recordCommand(nonce, true))
  }

  function start() {
    if (active || operation !== "" || pendingLeave || nonce !== "") return
    recording = true
    conflict = ""
    exposed = false
    lost = false
    advance()
    limit.restart()
  }

  function advance() {
    if (transition.running) return
    if (pendingLeave) {
      pendingLeave = false
      if (nonce !== "") {
        operation = "leave"
        transition.exec(Keycombo.recordCommand(nonce, true))
        return
      }
    }
    if (active && operation !== "entered") {
      nonce = Date.now().toString() + "-" + Math.random().toString(36).slice(2)
      operation = "enter"
      transition.exec(Keycombo.recordCommand(nonce, false))
    }
  }

  function finished(submap, ok) {
    if (operation === "enter") {
      operation = "entered"
      if (!ok || submap !== "omafind-record") {
        stop()
        exposed = true
      }
    } else if (operation === "leave") {
      operation = ""
      if (ok) {
        nonce = ""
        pendingLeave = false
        conflict = ""
        if (accepted !== "") recorded(accepted)
      } else {
        pendingLeave = true
        if (leaveRetries > 0) {
          leaveRetries--
          advance()
          return
        }
        accepted = ""
        conflict = "Hyprland could not leave recording mode. Close setup to retry, or press Super Esc."
        return
      }
      accepted = ""
    }
    advance()
  }

  function pollSubmap() {
    if (!active || operation !== "entered" || submapQuery.running) return
    polledNonce = nonce
    submapQuery.running = true
  }

  function checkSubmap(submap) {
    if (polledNonce !== nonce || !Keycombo.recordingSubmapLost(active ? "shortcut" : "", operation, submap)) return
    stop()
    lost = true
  }

  function stop() {
    if ((!active && nonce === "") || operation === "leave") return
    recording = false
    conflict = ""
    exposed = false
    limit.stop()
    pendingLeave = true
    leaveRetries = 1
    advance()
  }

  function capture(key, modifiers) {
    if (!active) return
    limit.restart()
    var parts = Keycombo.comboFromQt(key, modifiers)
    if (parts === null) return
    if (parts === "cancel") {
      stop()
      return
    }
    if (operation !== "entered") return
    var message = Keycombo.checkCombo(parts, binds)
    if (message) {
      conflict = message
      return
    }
    accepted = Keycombo.toHyprland(parts)
    stop()
  }

  Process {
    id: transition
    stdout: StdioCollector {
      id: enterOutput
      waitForEnd: true
    }
    onExited: (exitCode, exitStatus) => recorder.finished(enterOutput.text.trim(), exitCode === 0 && exitStatus === 0)
  }

  Process {
    id: submapQuery
    command: ["hyprctl", "submap"]
    stdout: StdioCollector {
      id: submapOutput
      waitForEnd: true
    }
    onExited: (exitCode, exitStatus) => recorder.checkSubmap(submapOutput.text)
  }

  Timer {
    interval: 1000
    repeat: true
    running: recorder.active
    onTriggered: recorder.pollSubmap()
  }

  Timer {
    id: limit
    interval: 30000
    onTriggered: recorder.stop()
  }
}
