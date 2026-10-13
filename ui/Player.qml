import QtQuick
import QtMultimedia
import Quickshell
import Quickshell.Io
import qs.Commons
import "../lib/playback.js" as Playback

// Ctrl Space playback. Audio plays in mpv over its IPC socket; video plays in the preview
// through QtMultimedia, which only honours a seek once the media has loaded.
Item {
  id: root

  property var playback: Playback.initial()
  property string kind: ""
  property var videoOutput: null
  readonly property bool started: playback.id !== null
  readonly property bool playing: playback.playing
  readonly property real position: playback.position
  readonly property string socketPath: Quickshell.env("XDG_RUNTIME_DIR") + "/omafind/mpv.sock"
  property real pendingSeek: -1
  property var ipc: null
  property int ipcAttempts: 0
  property var mpv: null
  property int processGeneration: 0

  function toggle(item) {
    var next = Playback.reduce(playback, {type: "toggle", item: item})
    if (next.command && next.command.op === "start") {
      stopBackends()
      kind = item.kind
    }
    apply(next)
  }

  function select(id) {
    apply(Playback.reduce(playback, {type: "selection", id: id}))
  }

  function stop() {
    if (playback.id === null) return
    apply(Playback.reduce(playback, {type: "selection", id: null}))
  }

  function apply(result) {
    playback = result.state
    var command = result.command
    if (!command) return
    if (command.op === "start") {
      if (kind === "video") {
        pendingSeek = command.start * 1000
        media.source = Util.fileUrl(command.path)
      } else {
        mpv = mpvComponent.createObject(root, {generation: ++processGeneration,
          command: Playback.mpvArgs(command.path, command.start, socketPath)})
        mpv.running = true
        ipcAttempts = 0
        connectIpc.restart()
      }
    } else if (command.op === "pause") {
      if (kind === "video") media.pause()
      else sendIpc(["set_property", "pause", true])
    } else if (command.op === "resume") {
      if (kind === "video") media.play()
      else sendIpc(["set_property", "pause", false])
    } else if (command.op === "stop") {
      stopBackends()
    }
  }

  function stopBackends() {
    pendingSeek = -1
    media.stop()
    media.source = ""
    connectIpc.stop()
    closeIpc()
    processGeneration += 1
    var old = mpv
    mpv = null
    if (old && old.running) old.running = false
    kind = ""
  }

  function ended() {
    stopBackends()
    playback = Playback.reduce(playback, {type: "ended"}).state
  }

  function sendIpc(command, requestId) {
    if (!ipc || !ipc.connected) return
    var message = {command: command}
    if (requestId) message.request_id = requestId
    ipc.write(JSON.stringify(message) + "\n")
    ipc.flush()
  }

  function closeIpc() {
    if (!ipc) return
    var old = ipc
    ipc = null
    old.connected = false
    old.destroy()
  }

  Component {
    id: mpvComponent
    Process {
      property int generation: 0
      onExited: {
        if (generation === root.processGeneration && root.kind === "audio") root.ended()
        destroy()
      }
    }
  }

  // mpv creates its socket a moment after it starts; a Quickshell Socket never retries, so each try is new.
  Timer {
    id: connectIpc
    interval: 100
    repeat: true
    onTriggered: {
      if (root.ipc && root.ipc.connected) {
        stop()
        return
      }
      root.closeIpc()
      if (++root.ipcAttempts > 30) {
        stop()
        return
      }
      root.ipc = ipcComponent.createObject(root)
      root.ipc.connected = true
    }
  }

  Component {
    id: ipcComponent
    Socket {
      path: root.socketPath
      parser: SplitParser {
        onRead: data => {
          try {
            var reply = JSON.parse(data)
            if (reply.request_id === 1 && typeof reply.data === "number")
              root.playback = Playback.reduce(root.playback, {type: "position", seconds: reply.data}).state
          } catch (error) {}
        }
      }
    }
  }

  Timer {
    interval: 100
    repeat: true
    running: root.kind === "audio" && root.playing
    onTriggered: root.sendIpc(["get_property", "time-pos"], 1)
  }

  MediaPlayer {
    id: media
    videoOutput: root.videoOutput
    audioOutput: AudioOutput {}
    onMediaStatusChanged: {
      if (mediaStatus === MediaPlayer.LoadedMedia && root.pendingSeek >= 0) {
        position = root.pendingSeek
        root.pendingSeek = -1
        if (root.playing) play()
      } else if (mediaStatus === MediaPlayer.EndOfMedia && root.kind === "video") {
        root.ended()
      }
    }
    onPositionChanged: {
      if (root.kind === "video" && root.pendingSeek < 0 && playbackState === MediaPlayer.PlayingState)
        root.playback = Playback.reduce(root.playback, {type: "position", seconds: position / 1000}).state
    }
  }

  Component.onDestruction: stopBackends()
}
