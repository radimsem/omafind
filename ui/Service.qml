import QtQuick
import Quickshell
import Quickshell.Io
import "../lib/Backoff.js" as Backoff
import "../lib/Protocol.js" as Protocol
import "../lib/Connection.js" as Connection
import "../lib/discovery.js" as Discovery
import "../lib/errors.js" as Errors
import "../lib/Settings.js" as Settings
import "../lib/Update.js" as Update
import "../lib/volumes.js" as Volumes
import "." as Parts

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
  // Each surface's latest failure: an error object (docs/ipc.md "Errors") or null.
  property var searchError: null

  // Setup (issue #5). The shell entry, parsed from shell.json, and the latest daemon facts.
  property var settingsEntry: ({})
  readonly property var settings: Settings.normalize(settingsEntry)
  property var runtimeProgress: null
  // The lib/discovery.js state: scans, walks, counts and cached folder children.
  property var discovery: Discovery.initial()
  property var folderError: null
  property var fsList: null
  property var progress: null
  property bool indexPending: false
  property var binds: []
  property bool bindsReady: false
  property var bindsError: null
  // The "Find files" row in the Omarchy menu: true, false, or null until a daemon reports it.
  property var menuRow: null
  property var engineError: null
  property var indexError: null
  property bool helperRunning: false
  // Issue #16: the lib/Update.js state. `updateRun` marks a helperSetup run started by an update;
  // `updateQueued` holds one back while a setup the user started is still running.
  property var update: Update.initial()
  property bool updateRun: false
  property bool updateQueued: false
  property bool runtimeAsked: false
  property string indexVolume: ""

  // Drives (issue #6). `volumes` is the lib/volumes.js state; `clock` advances while a toast or the
  // reconcile footer waits on a deadline. A drive scan lands in discovery.driveDiscover.
  property var volumes: Volumes.initial()
  property real clock: Date.now()
  property var driveError: null
  readonly property var ignoredVolumes: Array.isArray(settings.ignoredVolumes) ? settings.ignoredVolumes
    : Array.isArray(settingsEntry.ignoredVolumes) ? settingsEntry.ignoredVolumes.filter(uuid => typeof uuid === "string" && uuid !== "")
    : []
  readonly property bool ticking: volumes.toasts.some(toast => toast.until !== null)
    || (!!volumes.reconcile && volumes.reconcile.done_at !== null && clock < volumes.reconcile.done_at + 1250)
  readonly property string pluginDir: decodeURIComponent(Qt.resolvedUrl("..").toString().replace(/^file:\/\//, "")).replace(/\/$/, "")

  signal resultsReceived(var reply)
  signal previewReceived(var reply)
  signal itemFailed(var reply)
  signal itemOpened(var reply)
  signal openFailed(var reply)
  signal warmFailed(var error)
  signal statusReceived(var reply)
  signal childrenReceived(string path)
  signal fsListReceived(var reply)
  signal setupFailed(string forType, var error)
  // A reconciled drive changed what a search can find.
  signal volumesRefreshed()

  function warm() {
    searchError = null
    return send({t: "warm"})
  }

  function online() {
    return !!socket && socket.connected && ready
  }

  function send(message) {
    if (!online()) return false
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
  function startIndexing(roots, volume) {
    indexError = null
    if (volume) driveError = null
    var changes = volume ? {roots: roots} : {roots: roots, setupDone: true}
    if (!persist(changes)) {
      var failure = Errors.wrap(volume
        ? "Could not save the folders to shell.json. Check that the omafind plugin is enabled, then press Index this drive again."
        : "Could not save the folders to shell.json. Check that the omafind plugin is enabled, then press Start indexing again.")
      if (volume) driveError = failure
      else folderError = failure
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
    reduceDiscovery({type: "scan-drive", uuid: uuid, online: online()})
    return discovery.driveScanning
  }

  function reduceDiscovery(event) {
    var result = Discovery.reduce(discovery, event)
    discovery = result.state
    for (var i = 0; i < result.effects.length; i++) runEffect(result.effects[i])
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
    case "error":
      root[effect.surface] = effect.error
      break
    case "children":
      childrenReceived(effect.path)
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
    helperRunning = true
    helperSetup.running = true
  }

  function runtimeInstall() {
    engineError = null
    return send({t: "runtime_install"})
  }
  function runtimePause() { return send({t: "runtime_pause"}) }
  function requestRuntimeStatus() { return send({t: "runtime_status"}) }
  function requestProgress() { return send({t: "index_progress"}) }
  function retryFailed(code) { return send({t: "retry_failed", code: code}) }

  function scan() {
    reduceDiscovery({type: "scan", online: online()})
    return discovery.scanning
  }

  function requestChildren(path) { reduceDiscovery({type: "children", path: path, online: online()}) }
  function stopDiscovery() { reduceDiscovery({type: "stop", online: online()}) }

  function listDirs(path) { return send({t: "fs_list", path: path}) }

  // Port of omaone's runSetup: bin/omafind setup installs the venv and enables the unit.
  function installHelper() {
    if (helperRunning) return
    engineError = null
    helperRunning = true
    helperSetup.running = true
  }

  function getBinds() {
    bindsReady = false
    bindsError = null
    if (!send({t: "binds_get"})) bindsError = Errors.offline()
  }

  function saveShortcut(chord, menuRow, done) {
    if (!persist({shortcut: chord})) {
      done(false, "Could not save the shortcut to shell.json. Check that the omafind plugin is enabled.")
      return
    }
    var steps = [["bindings", "write", "--chord", chord]]
    if (menuRow) steps.push(["bindings", "menu", "add"])
    runSteps(steps, done)
  }

  function setMenuRow(on, done) {
    runSteps([["bindings", "menu", on ? "add" : "remove"]], (ok, line) => {
      if (ok) menuRow = on
      done(ok, line)
    })
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
    reduceDiscovery({type: "offline"})
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
      message.degraded = Errors.wrap(message.degraded)
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
      searchError = Errors.from(message)
      warmFailed(searchError)
      break
    case "status":
      status = message
      statusReceived(message)
      break
    case "binds":
      binds = Array.isArray(message.binds) ? message.binds : []
      menuRow = typeof message.menu === "boolean" ? message.menu : null
      bindsReady = true
      bindsError = null
      break
    case "runtime_progress":
      runtimeProgress = message
      engineError = message.state === "failed" ? Errors.from(message) : null
      break
    case "discover_result":
    case "discover_counts":
    case "discover_children":
      reduceDiscovery({type: message.t, message: message})
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
    var error = Errors.from(message)
    var surface = errorSurface(message.for, discovery.driveScanning)
    reduceDiscovery({type: "failed", for: message.for})
    if (message.for === "binds_get") bindsReady = false
    root[surface] = error
    setupFailed(message.for, error)
  }

  // Each request reports on one surface. Requests with no surface of their own report on step 1.
  // Errors carry no volume, so a failed discover_start is the drive scan's while one runs.
  function errorSurface(kind, driveScan) {
    switch (kind) {
    case "discover_start":
      return driveScan ? "driveError" : "folderError"
    case "discover_stop":
    case "discover_children":
    case "fs_list":
      return "folderError"
    case "drive_decision":
      return "driveError"
    case "binds_get":
      return "bindsError"
    case "index_start":
    case "index_progress":
    case "retry_failed":
      return "indexError"
    default:
      return "engineError"
    }
  }

  // `bin/omafind setup --json` ends stdout with {"ok": false, "error": {...}}; stderr is the fallback.
  function helperFailure(stdout, stderr) {
    var reply = null
    try {
      reply = JSON.parse(lastLine(stdout))
    } catch (error) {
      reply = null
    }
    if (reply && reply.ok === false && reply.error) return Errors.wrap(reply.error)
    return Errors.wrap(lastLine(stderr) || "The omafind helper could not be installed.")
  }

  function lastLine(text) {
    var lines = String(text || "").split("\n").map(line => line.trim()).filter(line => line !== "")
    return lines.length ? lines[lines.length - 1] : ""
  }

  function receiveState(message) {
    if (["ready", "missing"].indexOf(message.runtime) === -1
        || ["ready", "missing"].indexOf(message.model) === -1
        || ["stopped", "text", "full"].indexOf(message.embedder) === -1) return
    daemonState = message
    reduceUpdate({type: "daemon", build: typeof message.build === "string" ? message.build : ""})
    if (message.embedder !== "stopped") searchError = null
    connection = Connection.reduce(connection, {type: "state"})
    if (ready && bindsError && bindsError.code === "daemon-offline") getBinds()
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
    command: [root.pluginDir + "/bin/omafind", "setup", "--json"]
    stdout: StdioCollector { id: helperOut; waitForEnd: true }
    stderr: StdioCollector { id: helperErr; waitForEnd: true }
    onExited: (exitCode, exitStatus) => {
      var ok = exitCode === 0 && exitStatus === 0
      var failure = ok ? null : root.helperFailure(helperOut.text, helperErr.text)
      root.helperRunning = false
      if (root.updateRun) {
        root.updateRun = false
        root.reduceUpdate({type: "setup-exited", ok: ok, line: root.lastLine(helperErr.text), error: failure})
      } else {
        root.engineError = failure
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
