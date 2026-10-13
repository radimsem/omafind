import QtQuick
import Quickshell
import Quickshell.Io
import "lib/Backoff.js" as Backoff
import "lib/Protocol.js" as Protocol
import "lib/Connection.js" as Connection
import "lib/Settings.js" as Settings

Item {
  id: root

  property var shell: null
  property var manifest: null
  property var connection: Connection.initial()
  property var daemonState: ({t: "state", v: 1, runtime: "missing", model: "missing", embedder: "stopped"})
  readonly property string runtime: daemonState.runtime
  readonly property string model: daemonState.model
  readonly property string embedder: daemonState.embedder
  property var socket: null
  property bool attemptOpen: false
  readonly property bool ready: connection.socket === "ready"
  // The latest reply per message type. `results` keeps every seq; the view drops stale ones.
  property var results: null
  property var preview: null
  property var status: null
  property string warmFailure: ""

  // Setup (issue #5). The shell entry, parsed from shell.json, and the latest daemon facts.
  property var settingsEntry: ({})
  readonly property var settings: Settings.normalize(settingsEntry)
  property var runtimeProgress: null
  property var discover: null
  property string discoverError: ""
  property bool scanning: false
  // Absolute root -> discover_tree reply.
  property var trees: ({})
  property var fsList: null
  property var progress: null
  property bool indexPending: false
  // Chord -> "free", "ours", {conflict: line}, or null while its check runs.
  property var bindingChecks: ({})
  property string setupError: ""
  property bool helperRunning: false
  property bool runtimeAsked: false
  readonly property string pluginDir: decodeURIComponent(Qt.resolvedUrl(".").toString().replace(/^file:\/\//, "")).replace(/\/$/, "")

  signal resultsReceived(var reply)
  signal previewReceived(var reply)
  signal itemFailed(var reply)
  signal itemOpened(var reply)
  signal openFailed(var reply)
  signal warmFailed(string reason)
  signal statusReceived(var reply)
  signal treeReceived(var reply)
  signal fsListReceived(var reply)
  signal setupFailed(string forType, string reason)

  function warm() {
    warmFailure = ""
    return send({t: "warm"})
  }

  function send(message) {
    if (!socket || !socket.connected || !ready) return false
    socket.write(Protocol.encode(message))
    socket.flush()
    return true
  }

  // updateEntryInline replaces the whole entry, so every write sends the merged entry.
  function persist(changes) {
    if (!shell || !manifest || typeof shell.updateEntryInline !== "function") return false
    var merged = Settings.merge(settingsEntry, changes)
    if (JSON.stringify(merged) === JSON.stringify(settingsEntry)) return true
    if (!shell.updateEntryInline(manifest.id, merged)) return false
    settingsEntry = merged
    return true
  }

  // The daemon reads settings when index_start arrives, so the request waits for the shell's
  // off-thread write to land in shell.json (or 2 s, whichever comes first).
  function startIndexing(roots, codeRoots) {
    setupError = ""
    if (!persist({roots: roots, codeRoots: codeRoots, setupDone: true})) {
      setupError = "Could not save the folders to shell.json. Check that the omafind plugin is enabled, then press Start indexing again."
      return false
    }
    indexPending = true
    indexTimer.restart()
    return true
  }

  function sendIndexStart() {
    indexTimer.stop()
    if (!indexPending) return
    indexPending = false
    send({t: "index_start"})
  }

  function runtimeInstall() { return send({t: "runtime_install"}) }
  function runtimePause() { return send({t: "runtime_pause"}) }
  function requestRuntimeStatus() { return send({t: "runtime_status"}) }

  function scan() {
    discoverError = ""
    scanning = send({t: "discover_start"})
    return scanning
  }

  function requestTree(root) { return send({t: "discover_tree", root: root}) }
  function listDirs(path) { return send({t: "fs_list", path: path}) }

  // Port of omaone's runSetup: bin/omafind setup installs the venv and enables the unit.
  function installHelper() {
    if (helperRunning) return
    setupError = ""
    helperRunning = true
    helperSetup.running = true
  }

  function checkBindings(chords) {
    var next = Object.assign({}, bindingChecks)
    for (var i = 0; i < chords.length; i++) {
      next[chords[i]] = null
      bindingProcess.createObject(root, {chord: chords[i]})
    }
    bindingChecks = next
  }

  // Saves the chord, writes the Hyprland block, then the menu row when asked. `done(ok, errorLine)`.
  function saveShortcut(chord, menuRow, done) {
    if (!persist({shortcut: chord})) {
      done(false, "Could not save the shortcut to shell.json. Check that the omafind plugin is enabled.")
      return
    }
    var steps = [["bindings", "write", "--chord", chord]]
    if (menuRow) steps.push(["bindings", "menu", "add"])
    runSteps(steps, done)
  }

  function runSteps(steps, done) {
    if (!steps.length) {
      done(true, "")
      return
    }
    var step = cliProcess.createObject(root, {args: steps[0]})
    step.finished.connect((ok, line) => {
      if (ok) runSteps(steps.slice(1), done)
      else done(false, line)
    })
    step.running = true
  }

  function parseShellConfig(text) {
    var config = null
    try {
      config = JSON.parse(text)
    } catch (error) {
      return
    }
    settingsEntry = (manifest ? Settings.findEntry(config, manifest.id) : null) || {}
    if (indexPending && settings.setupDone) sendIndexStart()
  }

  function checkUnit() {
    unitCheck.running = true
  }

  function connectSocket() {
    if (connection.unit !== "enabled" || attemptOpen) return
    closeSocket()
    attemptOpen = true
    socket = socketComponent.createObject(root)
    socket.connected = true
  }

  function closeSocket() {
    if (!socket) return
    var old = socket
    socket = null
    old.connected = false
    old.destroy()
  }

  function attemptFailed() {
    if (!attemptOpen) return
    attemptOpen = false
    runtimeAsked = false
    scanning = false
    connection = Connection.reduce(connection, {type: "attempt-failed"})
    closeSocket()
    if (connection.unit === "enabled") reconnect.restart()
  }

  function receive(line) {
    var message = Protocol.decode(line)
    if (!message) return
    switch (message.t) {
    case "state":
      receiveState(message)
      break
    case "results":
      results = message
      resultsReceived(message)
      break
    case "error":
      // Setup errors name their request in `for` and carry no `seq` or `id`.
      if (typeof message.for === "string" && message.id === undefined && message.seq === undefined) {
        receiveSetupError(message)
        break
      }
      // Search errors echo `seq`; preview and open errors echo `id`.
      if (message.id !== undefined) itemFailed(message)
      else {
        results = message
        resultsReceived(message)
      }
      break
    case "preview":
      preview = message
      previewReceived(message)
      break
    case "opened":
      itemOpened(message)
      break
    case "open_failed":
      openFailed(message)
      break
    case "warm_failed":
      warmFailure = typeof message.reason === "string" ? message.reason : ""
      warmFailed(warmFailure)
      break
    case "status":
      status = message
      statusReceived(message)
      break
    case "runtime_progress":
      runtimeProgress = message
      break
    case "discover_result":
      scanning = false
      discoverError = ""
      discover = message
      break
    case "discover_tree":
      var nextTrees = Object.assign({}, trees)
      nextTrees[message.abs || message.root] = message
      trees = nextTrees
      treeReceived(message)
      break
    case "fs_list":
      fsList = message
      fsListReceived(message)
      break
    case "progress":
      progress = message
      break
    }
  }

  function receiveSetupError(message) {
    var reason = typeof message.reason === "string" ? message.reason : ""
    if (message.for === "discover_start") {
      scanning = false
      discoverError = reason
    } else {
      setupError = reason
    }
    setupFailed(message.for, reason)
  }

  function receiveState(message) {
    if (["ready", "missing"].indexOf(message.runtime) === -1
        || ["ready", "missing"].indexOf(message.model) === -1
        || ["stopped", "text", "full"].indexOf(message.embedder) === -1) return
    daemonState = message
    if (message.embedder !== "stopped") warmFailure = ""
    connection = Connection.reduce(connection, {type: "state"})
    if (ready && !runtimeProgress && !runtimeAsked) runtimeAsked = requestRuntimeStatus()
  }

  Component.onCompleted: checkUnit()

  FileView {
    id: shellConfig
    path: Quickshell.env("HOME") + "/.config/omarchy/shell.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.parseShellConfig(text())
  }

  onManifestChanged: if (shellConfig.loaded) parseShellConfig(shellConfig.text())

  // Sends index_start even if the shell.json change never shows up.
  Timer {
    id: indexTimer
    interval: 2000
    onTriggered: root.sendIndexStart()
  }

  Process {
    id: helperSetup
    command: [root.pluginDir + "/bin/omafind", "setup"]
    stderr: SplitParser {
      splitMarker: "\n"
      onRead: data => {
        if (data.trim()) root.setupError = data.trim()
      }
    }
    onExited: (exitCode, exitStatus) => {
      root.helperRunning = false
      if (exitCode === 0 && exitStatus === 0) root.setupError = ""
      root.checkUnit()
    }
  }

  // `bin/omafind bindings check --chord C`: exit 0 is free or ours, exit 2 a conflict line.
  Component {
    id: bindingProcess
    Process {
      id: check
      property string chord: ""
      command: [root.pluginDir + "/bin/omafind", "bindings", "check", "--chord", chord]
      running: true
      stdout: StdioCollector { id: checkOut; waitForEnd: true }
      onExited: (exitCode, exitStatus) => {
        var line = checkOut.text.trim()
        var next = Object.assign({}, root.bindingChecks)
        next[chord] = exitCode === 0 ? (line.indexOf("free") >= 0 ? "free" : "ours")
          : {conflict: line || "Could not read your Hyprland bindings."}
        root.bindingChecks = next
        check.destroy()
      }
    }
  }

  Component {
    id: cliProcess
    Process {
      id: step
      property var args: []
      signal finished(bool ok, string line)
      command: [root.pluginDir + "/bin/omafind"].concat(args)
      stdout: StdioCollector { id: stepOut; waitForEnd: true }
      stderr: StdioCollector { id: stepErr; waitForEnd: true }
      onExited: (exitCode, exitStatus) => {
        var lines = (stepErr.text.trim() || stepOut.text.trim()).split("\n")
        step.finished(exitCode === 0 && exitStatus === 0, exitCode === 0 ? "" : lines[lines.length - 1])
        step.destroy()
      }
    }
  }

  Process {
    id: unitCheck
    command: ["systemctl", "--user", "is-enabled", "omafind.service"]
    stdout: StdioCollector {
      id: unitOutput
      waitForEnd: true
    }
    onExited: (exitCode, exitStatus) => {
      var unitState = unitOutput.text.trim()
      var enabled = exitCode === 0 && exitStatus === 0
        && (unitState === "enabled" || unitState === "enabled-runtime")
      root.connection = Connection.reduce(root.connection, {type: "unit", enabled: enabled})
      if (enabled) {
        root.connectSocket()
      } else {
        reconnect.stop()
        root.attemptOpen = false
        root.closeSocket()
      }
    }
  }

  // A Quickshell Socket never connects again after an error, so each attempt gets a new one.
  Component {
    id: socketComponent
    Socket {
      id: attempt
      path: Quickshell.env("XDG_RUNTIME_DIR") + "/omafind/ui.sock"
      parser: SplitParser {
        splitMarker: "\n"
        onRead: data => {
          if (attempt === root.socket) root.receive(data)
        }
      }
      onConnectionStateChanged: {
        if (attempt !== root.socket) return
        if (connected) {
          root.connection = Connection.reduce(root.connection, {type: "socket-open"})
          write(Protocol.encode(Protocol.hello()))
          flush()
        } else {
          root.attemptFailed()
        }
      }
      onError: error => {
        if (attempt === root.socket) root.attemptFailed()
      }
    }
  }

  // The plugin can load before `bin/omafind setup` enables the unit, so a missing unit is checked again.
  Timer {
    interval: 2000
    repeat: true
    running: root.connection.unit !== "enabled" && !unitCheck.running
    onTriggered: root.checkUnit()
  }

  Timer {
    id: reconnect
    interval: Backoff.delay(root.connection.failures)
    repeat: false
    onTriggered: root.connectSocket()
  }
}
