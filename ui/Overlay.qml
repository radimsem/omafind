import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import qs.Commons
import "." as Plugin
import "." as Parts
import "../lib/errors.js" as Errors
import "../lib/setup.js" as Setup

// The search overlay. The shell calls only open(payload) and close(), and reads `opened` to toggle.
Item {
  id: root

  property var shell: null
  property var manifest: null
  property bool opened: false
  // Writable: the host assigns `service` on load.
  property var service: shell && manifest ? shell.serviceFor(manifest.id) : null
  property string view: "search"
  // The volume UUID the drive view shows.
  property string driveVolume: ""
  // Setup opens at the Folders step even when setup is done (Settings, "Change folders").
  property bool setupFolders: false
  // The window stays mapped through the 120 ms close animation.
  property bool mapped: false
  property real openedAt: 0
  property bool timing: false

  function open(payload) {
    if (setup.item) setup.item.stop()
    if (settingsView.item) settingsView.item.stop()
    var parsed = {}
    try {
      parsed = payload ? JSON.parse(payload) : {}
    } catch (error) {
      parsed = {}
    }
    var drive = !!parsed && parsed.view === "drive" && typeof parsed.volume === "string" && parsed.volume !== ""
    // A dialog already showing this drive starts over; a new one scans when its uuid is set.
    var again = drive && view === "drive" && driveVolume === parsed.volume && !!driveLoader.item
    if (drive) driveVolume = parsed.volume
    setupFolders = false
    view = drive ? "drive" : Setup.opensSetup(parsed && parsed.view, service ? service.settings.setupDone : true,
      service ? service.runtimeProgress : null) ? "setup" : "search"
    if (again) {
      driveLoader.item.reset()
      driveLoader.item.begin()
    }
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
    if (setup.item) {
      setup.item.pickFolders = false
      setup.item.reset()
    }
    if (service && view === "setup") {
      service.requestRuntimeStatus()
    } else if (service && view !== "drive") {
      service.warm()
      service.send({t: "status"})
    }
    Qt.callLater(focusView)
  }

  // "Save shortcut and open search" leaves setup for an empty search; Esc and Back leave Settings.
  function showSearch() {
    if (setup.item) setup.item.stop()
    if (settingsView.item) settingsView.item.stop()
    if (service && view !== "search") service.stopDiscovery()
    view = "search"
    searchView.reset()
    if (service) {
      service.warm()
      service.send({t: "status"})
    }
    Qt.callLater(focusView)
  }

  function showSettings() {
    searchView.stopPlayback()
    view = "settings"
    Qt.callLater(focusView)
  }

  function showFolders() {
    if (settingsView.item) settingsView.item.stop()
    setupFolders = true
    view = "setup"
    if (setup.item) {
      setup.item.pickFolders = true
      setup.item.reset()
    }
    if (service) service.requestRuntimeStatus()
    Qt.callLater(focusView)
  }

  // Idempotent: shell.hide() calls it again after dismiss().
  function close() {
    if (setup.item) setup.item.stop()
    if (settingsView.item) settingsView.item.stop()
    if (!opened) return
    opened = false
    if (service && view !== "search") service.stopDiscovery()
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
    else if (view === "drive" && driveLoader.item) driveLoader.item.focusFirst()
    else if (view === "setup" && setup.item) setup.item.focusFirst()
    else if (view === "settings" && settingsView.item) settingsView.item.focusFirst()
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
      readonly property var panelItem: root.view === "setup" ? setup.item : root.view === "drive" ? driveLoader.item
        : root.view === "settings" ? settingsView.item : null
      readonly property bool sized: !!panelItem
      width: Math.min(sized ? panelItem.panelWidth : Plugin.Tokens.overlayWidth, panel.width - Style.gapsOut * 2)
      height: Math.min(sized ? panelItem.panelHeight : Plugin.Tokens.overlayHeight,
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
        onSettingsRequested: root.showSettings()
        onToastRequested: (title, tokens, error) => toast.show(title, tokens, error)
        onOpenStarted: (item, how, message) => {
          root.pendingOpen = {id: item.id, how: how, item: item, message: message, reply: null, closed: false}
          openTimeout.restart()
          closeTimer.restart()
        }
      }

      Item {
        id: keyCatcher
        anchors.fill: parent
        anchors.margins: card.border.width
        visible: root.view !== "search"
        Keys.onPressed: event => {
          if (card.panelItem) card.panelItem.handleKey(event)
        }

        Loader {
          id: setup
          anchors.fill: parent
          active: root.view === "setup"
          source: "SetupView.qml"
          onLoaded: {
            item.pickFolders = root.setupFolders
            item.service = Qt.binding(() => root.service)
          }
        }

        Connections {
          target: setup.item
          ignoreUnknownSignals: true
          function onCloseRequested() { root.dismiss() }
          function onSearchRequested() { root.showSearch() }
        }

        Loader {
          id: settingsView
          anchors.fill: parent
          active: root.view === "settings"
          source: "SettingsView.qml"
          onLoaded: {
            item.service = Qt.binding(() => root.service)
            item.reset()
          }
        }

        Connections {
          target: settingsView.item
          ignoreUnknownSignals: true
          function onBackRequested() { root.showSearch() }
          function onFoldersRequested() { root.showFolders() }
        }

        Loader {
          id: driveLoader
          anchors.fill: parent
          active: root.view === "drive" && root.driveVolume !== ""
          source: "DriveDialog.qml"
          onLoaded: {
            item.service = Qt.binding(() => root.service)
            item.uuid = Qt.binding(() => root.driveVolume)
            Qt.callLater(root.focusView)
          }
        }

        Connections {
          target: driveLoader.item
          ignoreUnknownSignals: true
          function onCloseRequested() { root.dismiss() }
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
  // The last open that failed, so the toast's Retry can send it again.
  property var failedOpen: null

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

  function failOpen(error) {
    var failed = pendingOpen
    closeTimer.stop()
    openTimeout.stop()
    searchView.flash = ""
    pendingOpen = null
    failedOpen = {message: failed.message, item: failed.item, how: failed.how}
    toast.showError(error)
  }

  // The reply to a retried open is announced as a first open is.
  function retryOpen() {
    var failed = failedOpen
    failedOpen = null
    toast.dismiss()
    if (!failed || !failed.message || !service || !service.send(failed.message)) return
    pendingOpen = {id: failed.item.id, how: failed.how, item: failed.item, message: failed.message,
      reply: null, closed: !opened}
    openTimeout.restart()
    if (opened) closeTimer.restart()
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
      if (root.pendingOpen && message.id === root.pendingOpen.id) root.failOpen(Errors.from(message))
    }
    function onItemFailed(message) {
      if (root.pendingOpen && message.for === "open" && message.id === root.pendingOpen.id)
        root.failOpen(Errors.from(message))
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
    onRetryRequested: root.retryOpen()
  }
}
