import QtQuick
import Quickshell
import Quickshell.Io
import "lib/Backoff.js" as Backoff
import "lib/Protocol.js" as Protocol
import "lib/Connection.js" as Connection

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

  signal resultsReceived(var reply)
  signal previewReceived(var reply)
  signal itemFailed(var reply)
  signal itemOpened(var reply)
  signal openFailed(var reply)
  signal warmFailed(string reason)
  signal statusReceived(var reply)

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
    }
  }

  function receiveState(message) {
    if (["ready", "missing"].indexOf(message.runtime) === -1
        || ["ready", "missing"].indexOf(message.model) === -1
        || ["stopped", "text", "full"].indexOf(message.embedder) === -1) return
    daemonState = message
    if (message.embedder !== "stopped") warmFailure = ""
    connection = Connection.reduce(connection, {type: "state"})
  }

  Component.onCompleted: checkUnit()

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
