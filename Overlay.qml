import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import qs.Commons
import "." as Plugin
import "ui" as Parts

// The search overlay. The shell calls only open(payload) and close(), and reads `opened` to toggle.
Item {
  id: root

  property var shell: null
  property var manifest: null
  property bool opened: false
  // Writable: the host assigns `service` on load.
  property var service: shell && manifest ? shell.serviceFor(manifest.id) : null
  property string view: "search"
  // The window stays mapped through the 120 ms close animation.
  property bool mapped: false
  property real openedAt: 0
  property bool timing: false

  function open(payload) {
    var parsed = {}
    try {
      parsed = payload ? JSON.parse(payload) : {}
    } catch (error) {
      parsed = {}
    }
    view = parsed && parsed.view === "setup" || (service && !service.settings.setupDone) ? "setup" : "search"
    openedAt = Date.now()
    timing = true
    console.log("omafind open start " + openedAt)
    unmap.stop()
    closeTimer.stop()
    if (pendingOpen) {
      pendingOpen.closed = true
      if (pendingOpen.reply) announce()
    }
    searchView.reset()
    if (!mapped) {
      panel.screen = focusedScreen()
    }
    opened = true
    mapped = true
    if (setup.item) setup.item.reset()
    if (service && view === "setup") {
      service.requestRuntimeStatus()
    } else if (service) {
      service.warm()
      service.send({t: "status"})
    }
    Qt.callLater(focusView)
  }

  // "Save shortcut and open search" leaves setup for an empty search.
  function showSearch() {
    view = "search"
    searchView.reset()
    if (service) {
      service.warm()
      service.send({t: "status"})
    }
    Qt.callLater(focusView)
  }

  // Idempotent: shell.hide() calls it again after dismiss().
  function close() {
    if (!opened) return
    opened = false
    closeTimer.stop()
    searchView.stopPlayback()
    searchView.flash = ""
    if (pendingOpen) {
      pendingOpen.closed = true
      if (pendingOpen.reply) announce()
    }
    unmap.restart()
  }

  function dismiss() {
    close()
    if (shell && typeof shell.hide === "function") shell.hide((manifest && manifest.id) || "radimsem.omafind")
  }

  function toggle() {
    if (opened) dismiss()
    else open("{}")
  }

  function focusView() {
    if (!opened) return
    if (view === "search") searchView.focusQuery()
    else if (setup.item) setup.item.focusFirst()
    else keyCatcher.forceActiveFocus()
  }

  function focusedScreen() {
    var name = Hyprland.focusedMonitor ? String(Hyprland.focusedMonitor.name) : ""
    var screens = Quickshell.screens
    for (var i = 0; i < screens.length; i++)
      if (screens[i].name === name) return screens[i]
    return screens.length ? screens[0] : null
  }

  Timer {
    id: unmap
    interval: 120
    onTriggered: {
      root.mapped = false
      searchView.reset()
    }
  }

  PanelWindow {
    id: panel
    visible: root.mapped
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "omafind"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: root.opened ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore

    // The scrim stops under the bar, as behind the Omarchy menu.
    Rectangle {
      anchors.fill: parent
      anchors.topMargin: Style.bar.sizeHorizontal
      color: Color.menu.scrim
      opacity: root.opened ? 1 : 0
      Behavior on opacity { NumberAnimation { duration: root.opened ? 140 : 120 } }
    }

    MouseArea {
      anchors.fill: parent
      enabled: root.opened
      onClicked: root.dismiss()
    }

    Rectangle {
      id: card
      readonly property bool sized: root.view === "setup" && !!setup.item
      width: Math.min(sized ? setup.item.panelWidth : Plugin.Tokens.overlayWidth, panel.width - Style.gapsOut * 2)
      height: Math.min(sized ? setup.item.panelHeight : Plugin.Tokens.overlayHeight,
        panel.height - Style.bar.sizeHorizontal - Style.gapsOut * 2)
      // M3: the setup panel resizes over 240 ms between steps; the search card never animates.
      Behavior on width {
        enabled: card.sized && root.opened
        NumberAnimation { duration: 240; easing.type: Easing.BezierSpline; easing.bezierCurve: Plugin.Tokens.ease }
      }
      Behavior on height {
        enabled: card.sized && root.opened
        NumberAnimation { duration: 240; easing.type: Easing.BezierSpline; easing.bezierCurve: Plugin.Tokens.ease }
      }
      x: Math.round((panel.width - width) / 2)
      y: Math.round((panel.height - height) / 2 + Plugin.Tokens.overlayOffset)
      radius: Style.cornerRadius
      color: Color.popups.background
      border.width: 2
      border.color: Color.popups.border
      opacity: root.opened ? 1 : 0
      transform: Translate {
        y: root.opened ? 0 : Style.space(8)
        Behavior on y {
          NumberAnimation {
            duration: root.opened ? 160 : 120
            easing.type: Easing.BezierSpline
            easing.bezierCurve: Plugin.Tokens.ease
          }
        }
      }
      Behavior on opacity {
        NumberAnimation {
          duration: root.opened ? 160 : 120
          easing.type: Easing.BezierSpline
          easing.bezierCurve: Plugin.Tokens.ease
        }
      }

      MouseArea { anchors.fill: parent; onClicked: {} }

      Plugin.SearchView {
        id: searchView
        objectName: "omafindSearch"
        anchors.fill: parent
        anchors.margins: card.border.width
        visible: root.view === "search"
        service: root.service
        pending: root.pendingOpen
        onCloseRequested: root.dismiss()
        onToastRequested: (title, tokens, error) => toast.show(title, tokens, error)
        onOpenStarted: (item, how) => {
          root.pendingOpen = {id: item.id, how: how, item: item, reply: null, closed: false}
          openTimeout.restart()
          closeTimer.restart()
        }
      }

      Item {
        id: keyCatcher
        anchors.fill: parent
        anchors.margins: card.border.width
        visible: root.view === "setup"
        Keys.onPressed: event => {
          if (setup.item) setup.item.handleKey(event)
        }

        Loader {
          id: setup
          anchors.fill: parent
          active: root.view === "setup"
          source: "SetupView.qml"
          onLoaded: item.service = Qt.binding(() => root.service)
        }

        Connections {
          target: setup.item
          ignoreUnknownSignals: true
          function onCloseRequested() { root.dismiss() }
          function onSearchRequested() { root.showSearch() }
        }
      }

      // Logs the time from open() to the first presented frame, for the open-time check.
      Connections {
        target: card.Window.window
        enabled: root.timing
        function onFrameSwapped() {
          if (!root.timing) return
          root.timing = false
          console.log("omafind open " + (Date.now() - root.openedAt) + " ms")
        }
      }
    }
  }

  property var pendingOpen: null

  function announce() {
    var pending = pendingOpen
    var tokens = [{k: "opener", v: pending.reply.opener, tone: "plain"}]
    if (pending.how === "reveal") {
      tokens.push({k: "path", v: searchView.folder(pending.item), tone: "plain"})
      toast.show("Show in folder", tokens, false)
    } else {
      if (pending.reply.at) tokens.push({k: "at", v: pending.reply.at, tone: "plain"})
      toast.show("Opening " + pending.item.name, tokens, false)
    }
    openTimeout.stop()
    pendingOpen = null
  }

  function failOpen(reason) {
    var name = pendingOpen.item.name
    closeTimer.stop()
    openTimeout.stop()
    searchView.flash = ""
    pendingOpen = null
    toast.show("Could not open " + name, [{k: "reason", v: reason, tone: "warn"}], true)
  }

  Connections {
    target: root.service
    function onItemOpened(message) {
      if (!root.pendingOpen || message.id !== root.pendingOpen.id) return
      root.pendingOpen.reply = message
      openTimeout.stop()
      if (root.pendingOpen.closed) root.announce()
    }
    function onOpenFailed(message) {
      if (root.pendingOpen && message.id === root.pendingOpen.id) root.failOpen(message.reason)
    }
    function onItemFailed(message) {
      if (root.pendingOpen && message.for === "open" && message.id === root.pendingOpen.id) root.failOpen("error")
    }
  }

  Timer {
    id: closeTimer
    interval: 260
    onTriggered: if (root.pendingOpen) root.dismiss()
  }

  Timer {
    id: openTimeout
    interval: 5000
    onTriggered: {
      root.pendingOpen = null
      searchView.flash = ""
    }
  }

  Parts.Toast {
    id: toast
  }
}
