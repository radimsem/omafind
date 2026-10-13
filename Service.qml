import QtQuick
import Quickshell
import Quickshell.Io
import "lib/Backoff.js" as Backoff
import "lib/Protocol.js" as Protocol
import "lib/Connection.js" as Connection
import "lib/Settings.js" as Settings
import "lib/Update.js" as Update
import "lib/volumes.js" as Volumes
import "ui" as Parts

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
  // Issue #16: the lib/Update.js state. `updateRun` marks a helperSetup run started by an update;
  // `updateQueued` holds one back while a setup the user started is still running.
  property var update: Update.initial()
  property bool updateRun: false
  property bool updateQueued: false
  property string updateLine: ""
  property bool runtimeAsked: false
  property string indexVolume: ""

  // Drives (issue #6). `volumes` is the lib/volumes.js state; `clock` advances while a toast or the
  // reconcile footer waits on a deadline. A drive scan lands in driveDiscover, never in discover.
  property var volumes: Volumes.initial()
  property real clock: Date.now()
  property var driveDiscover: null
  property bool driveScanning: false
  property string driveError: ""
  readonly property var ignoredVolumes: Array.isArray(settings.ignoredVolumes) ? settings.ignoredVolumes
    : Array.isArray(settingsEntry.ignoredVolumes) ? settingsEntry.ignoredVolumes.filter(uuid => typeof uuid === "string" && uuid !== "")
    : []
  readonly property bool ticking: volumes.toasts.some(toast => toast.until !== null)
    || (!!volumes.reconcile && volumes.reconcile.done_at !== null && clock < volumes.reconcile.done_at + 1250)
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
  // A reconciled drive changed what a search can find.
  signal volumesRefreshed()

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
  // off-thread write to land in shell.json (or 2 s, whichever comes first). A drive passes its
  // volume UUID and saves only the roots, so setup state stays as it was.
  function startIndexing(roots, codeRoots, volume) {
    setupError = ""
    var changes = volume ? {roots: roots} : {roots: roots, codeRoots: codeRoots, setupDone: true}
    if (!persist(changes)) {
      setupError = volume
        ? "Could not save the folders to shell.json. Check that the omafind plugin is enabled, then press Index this drive again."
        : "Could not save the folders to shell.json. Check that the omafind plugin is enabled, then press Start indexing again."
      return false
    }
    indexVolume = volume || ""
    indexPending = true
    indexTimer.restart()
    return true
  }

  function sendIndexStart() {
    indexTimer.stop()
    if (!indexPending) return
    indexPending = false
    send(indexVolume ? {t: "index_start", volume: indexVolume} : {t: "index_start"})
    indexVolume = ""
  }

  function scanDrive(uuid) {
    driveError = ""
    driveDiscover = null
    driveScanning = send({t: "discover_start", volume: uuid})
    return driveScanning
  }

  function reduceVolumes(event) {
    var result = Volumes.reduce(volumes, event)
    volumes = result.state
    for (var i = 0; i < result.effects.length; i++) runEffect(result.effects[i])
  }

  function runEffect(effect) {
    switch (effect.type) {
    case "persist":
      persist(effect.changes)
      break
    case "send":
      send(effect.message)
      break
    case "summon":
      if (shell && manifest && typeof shell.summon === "function")
        shell.summon(manifest.id, JSON.stringify(effect.payload))
      break
    case "research":
      volumesRefreshed()
      break
    }
  }

  // `choice` is "scan" or "ignore", from the New drive toast.
  function decideDrive(uuid, choice) {
    reduceVolumes({type: "decide", uuid: uuid, choice: choice, now: Date.now()})
  }

  function dismissToast(id) {
    reduceVolumes({type: "dismiss", id: id})
  }

  function reduceUpdate(event) {
    var result = Update.reduce(update, event)
    update = result.state
    for (var i = 0; i < result.effects.length; i++) {
      if (result.effects[i].type === "setup") runUpdate()
    }
  }

  function retryUpdate() { reduceUpdate({type: "retry"}) }

  // bin/omafind setup syncs the venv to the lock file and restarts the unit.
  function runUpdate() {
    if (helperRunning) {
      updateQueued = !updateRun
      return
    }
    updateRun = true
    updateLine = ""
    helperRunning = true
    helperSetup.running = true
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
    if (indexPending && (indexVolume ? settings.roots.some(r => r.volume === indexVolume) : settings.setupDone))
      sendIndexStart()
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
    driveScanning = false
    connection = Connection.reduce(connection, {type: "attempt-failed"})
    closeSocket()
    // A daemon that dies on import never sends `state`; status tells whether its venv is behind.
    if (connection.failures === 3 && update.phase === "idle" && !venvCheck.running)
      venvCheck.running = true
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
      if (message.volume) {
        driveScanning = false
        driveError = ""
        driveDiscover = message
        break
      }
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
    case "volume":
      if (typeof message.uuid === "string" && message.uuid)
        reduceVolumes({type: "volume", message: message, now: Date.now()})
      break
    case "reconcile":
      if (typeof message.uuid === "string" && message.uuid)
        reduceVolumes({type: "reconcile", message: message, now: Date.now()})
      break
    case "paused":
      reduceVolumes({type: "paused", message: message})
      break
    case "resumed":
      reduceVolumes({type: "resumed"})
      break
    }
  }

  function receiveSetupError(message) {
    var reason = typeof message.reason === "string" ? message.reason : ""
    // Errors carry no volume, so a failed discover_start is the drive scan's while one runs.
    if (message.for === "discover_start" && driveScanning) {
      driveScanning = false
      driveError = reason
    } else if (message.for === "discover_start") {
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
    reduceUpdate({type: "daemon", build: typeof message.build === "string" ? message.build : ""})
    if (message.embedder !== "stopped") warmFailure = ""
    connection = Connection.reduce(connection, {type: "state"})
    if (ready && !runtimeProgress && !runtimeAsked) runtimeAsked = requestRuntimeStatus()
  }

  Component.onCompleted: {
    reduceVolumes({type: "settings", ignoredVolumes: ignoredVolumes})
    checkUnit()
  }

  onIgnoredVolumesChanged: reduceVolumes({type: "settings", ignoredVolumes: ignoredVolumes})

  Timer {
    interval: 100
    repeat: true
    running: root.ticking
    onTriggered: {
      root.clock = Date.now()
      root.reduceVolumes({type: "tick", now: root.clock})
    }
  }

  // Stays mapped while the overlay is closed, so the drive buttons work from the desktop.
  Parts.DriveToast {
    service: root
  }

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
        if (!data.trim()) return
        if (root.updateRun) root.updateLine = data.trim()
        else root.setupError = data.trim()
      }
    }
    onExited: (exitCode, exitStatus) => {
      var ok = exitCode === 0 && exitStatus === 0
      root.helperRunning = false
      if (root.updateRun) {
        root.updateRun = false
        root.reduceUpdate({type: "setup-exited", ok: ok, line: root.updateLine})
      } else if (ok) {
        root.setupError = ""
      }
      if (root.updateQueued) {
        root.updateQueued = false
        root.runUpdate()
      }
      root.checkUnit()
    }
  }

  Process {
    id: venvCheck
    command: [root.pluginDir + "/bin/omafind", "status", "--json"]
    stdout: StdioCollector { id: venvCheckOut; waitForEnd: true }
    onExited: (exitCode, exitStatus) => {
      var details = null
      try {
        details = JSON.parse(venvCheckOut.text)
      } catch (error) {
        return
      }
      if (details && details.venv && typeof details.venv.state === "string")
        root.reduceUpdate({type: "venv", state: details.venv.state})
    }
  }

  // The build of the plugin this shell loaded, compared with the daemon's `state.build`.
  Process {
    id: localBuild
    command: [root.pluginDir + "/bin/omafind", "fingerprint"]
    running: true
    stdout: StdioCollector { id: localBuildOut; waitForEnd: true }
    stderr: StdioCollector { id: localBuildErr; waitForEnd: true }
    onExited: (exitCode, exitStatus) => {
      if (exitCode === 0 && exitStatus === 0 && localBuildOut.text.trim())
        root.reduceUpdate({type: "local", build: localBuildOut.text.trim()})
      else
        console.warn("omafind: no plugin build, so the daemon is not updated: " + localBuildErr.text.trim())
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
