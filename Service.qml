import QtQuick
import Quickshell
import Quickshell.Io
import "lib/Backoff.js" as Backoff
import "lib/Protocol.js" as Protocol
import "lib/Connection.js" as Connection
import "lib/errors.js" as Errors
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
  // Each surface's latest failure: an error object (docs/ipc.md "Errors") or null.
  property var searchError: null

  // Setup (issue #5). The shell entry, parsed from shell.json, and the latest daemon facts.
  property var settingsEntry: ({})
  readonly property var settings: Settings.normalize(settingsEntry)
  property var runtimeProgress: null
  property var discover: null
  property var folderError: null
  property bool scanning: false
  // Absolute folder -> rolled-up counts, merged from every discover_counts batch.
  property var discoverCounts: ({})
  // Walk root -> {done, seconds, error} from its latest batch.
  property var walks: ({})
  // Dataset folder -> {path, kind, files, named} from each walk's last batch.
  property var datasets: ({})
  property var repos: ({})
  property var worktrees: ({})
  // Folder -> {dirs, volume, error} from discover_children. `childrenAsked` stops a second request.
  property var childFolders: ({})
  property var childrenAsked: ({})
  property var fsList: null
  property var progress: null
  property bool indexPending: false
  property var binds: []
  property bool bindsReady: false
  property var bindsError: null
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
  // reconcile footer waits on a deadline. A drive scan lands in driveDiscover, never in discover.
  property var volumes: Volumes.initial()
  property real clock: Date.now()
  property var driveDiscover: null
  property bool driveScanning: false
  property var driveError: null
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
    indexError = null
    if (volume) driveError = null
    var changes = volume ? {roots: roots} : {roots: roots, codeRoots: codeRoots, setupDone: true}
    if (volume && Array.isArray(codeRoots)) changes.codeRoots = codeRoots
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
    driveError = null
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
    folderError = null
    scanning = send({t: "discover_start"})
    return scanning
  }

  function requestChildren(path) {
    if ((childFolders[path] && !childFolders[path].error) || childrenAsked[path]) return true
    var asked = Object.assign({}, childrenAsked)
    asked[path] = true
    if (!send({t: "discover_children", path: path})) return false
    childrenAsked = asked
    return true
  }
  function stopDiscovery() {
    scanning = false
    driveScanning = false
    // The daemon answers children requests still in flight with `discover_stop`.
    childrenAsked = {}
    var stopped = Object.assign({}, walks)
    for (var path in stopped) stopped[path] = Object.assign({}, stopped[path], {done: true})
    walks = stopped
    return send({t: "discover_stop"})
  }

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
    childrenAsked = {}
    var stopped = Object.assign({}, walks)
    for (var walkRoot in stopped) if (!stopped[walkRoot].done)
      stopped[walkRoot] = {done: true, seconds: null, error: "Connection lost"}
    walks = stopped
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
      bindsReady = true
      bindsError = null
      break
    case "runtime_progress":
      runtimeProgress = message
      engineError = message.state === "failed" ? Errors.from(message) : null
      break
    case "discover_result":
      if (Array.isArray(message.roots)) message.roots.forEach(entry => clearDiscovery(entry.path))
      if (message.volume) {
        driveScanning = false
        driveError = null
        driveDiscover = message
        break
      }
      scanning = false
      folderError = null
      discover = message
      break
    case "discover_counts":
      receiveCounts(message)
      break
    case "discover_children":
      var nextChildren = Object.assign({}, childFolders)
      nextChildren[message.path] = {dirs: Array.isArray(message.dirs) ? message.dirs : [],
        volume: typeof message.volume === "string" ? message.volume : "",
        error: errorText(message.error)}
      childFolders = nextChildren
      var childCounts = Object.assign({}, discoverCounts)
      nextChildren[message.path].dirs.forEach(dir => { if (dir.counts && !childCounts[dir.path]) childCounts[dir.path] = dir.counts })
      discoverCounts = childCounts
      var childSets = Object.assign({}, datasets)
      nextChildren[message.path].dirs.forEach(dir => {
        if (dir.evidence) childSets[dir.path] = Object.assign({path: dir.path}, dir.evidence)
      })
      datasets = childSets
      var childRepos = Object.assign({}, repos)
      var childTrees = Object.assign({}, worktrees)
      nextChildren[message.path].dirs.forEach(dir => {
        if (dir.repo) childRepos[dir.path] = {path: dir.path}
        if (dir.worktree) childTrees[dir.path] = {path: dir.path}
      })
      worktrees = childTrees
      repos = childRepos
      var pendingChildren = Object.assign({}, childrenAsked)
      delete pendingChildren[message.path]
      childrenAsked = pendingChildren
      childrenReceived(message.path)
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
    var surface = errorSurface(message.for, driveScanning)
    if (message.for === "discover_start") {
      if (driveScanning) driveScanning = false
      else scanning = false
    }
    if (message.for === "binds_get") bindsReady = false
    if (message.for === "discover_children") childrenAsked = {}
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

  // Walks and folder rows show a failure as one fact: the error's title.
  function errorText(value) {
    var error = Errors.wrap(value)
    return error ? error.title : ""
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

  // Clears counts, datasets and walks under `walkRoot`. Cached children stay: they hold the folder
  // lists and the volume of folders added outside every root. A drive mounted inside the root has
  // its own walk, and its snapshot may already have arrived, so its subtree stays.
  function clearDiscovery(walkRoot) {
    function under(path, root) { return path === root || path.indexOf(root.replace(/\/$/, "") + "/") === 0 }
    var nested = Object.keys(walks).filter(root => root !== walkRoot && under(root, walkRoot))
    function outside(path) { return !under(path, walkRoot) || nested.some(root => under(path, root)) }
    var counts = Object.assign({}, discoverCounts)
    var sets = Object.assign({}, datasets)
    var foundRepos = Object.assign({}, repos)
    var foundTrees = Object.assign({}, worktrees)
    for (var path in counts) if (!outside(path)) delete counts[path]
    for (var path in sets) if (!outside(path)) delete sets[path]
    for (var path in foundRepos) if (!outside(path)) delete foundRepos[path]
    for (var path in foundTrees) if (!outside(path)) delete foundTrees[path]
    // The folders step sorts when a walk finishes, so a rescan must not inherit the old finish.
    var nextWalks = Object.assign({}, walks)
    for (var path in nextWalks) if (!outside(path)) delete nextWalks[path]
    discoverCounts = counts
    datasets = sets
    repos = foundRepos
    worktrees = foundTrees
    walks = nextWalks
  }

  function receiveCounts(message) {
    if (typeof message.root !== "string" || !message.counts) return
    if (message.reset) clearDiscovery(message.root)
    var counts = Object.assign({}, discoverCounts)
    for (var path in message.counts) counts[path] = message.counts[path]
    discoverCounts = counts
    var nextWalks = Object.assign({}, walks)
    // `error` is the title, one fact in folder rows; `failure` keeps the object for the drive dialog.
    nextWalks[message.root] = {done: !!message.done, seconds: typeof message.seconds === "number" ? message.seconds : null,
      error: errorText(message.error), failure: Errors.wrap(message.error)}
    if (message.error) folderError = Errors.wrap(message.error)
    if (Array.isArray(message.datasets)) {
      var nextSets = Object.assign({}, datasets)
      message.datasets.forEach(entry => nextSets[entry.path] = entry)
      datasets = nextSets
    }
    if (Array.isArray(message.worktrees)) {
      var nextTrees = Object.assign({}, worktrees)
      message.worktrees.forEach(path => nextTrees[path] = {path: path})
      worktrees = nextTrees
    }
    if (Array.isArray(message.repos)) {
      var nextRepos = Object.assign({}, repos)
      message.repos.forEach(path => nextRepos[path] = {path: path})
      repos = nextRepos
    }
    walks = nextWalks
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
