.pragma library
.import "format.js" as Format

// QML supplies import namespaces; the Node loader shares one global context.
var F = typeof Format !== "undefined" ? Format : this

function initial() {
  return {toasts: [], drives: {}, reconcile: null, disk: null, ignored: []}
}

function reduce(state, event) {
  var next = {toasts: state.toasts.slice(), drives: Object.assign({}, state.drives),
    reconcile: state.reconcile, disk: state.disk, ignored: state.ignored.slice()}
  var effects = []
  var message = event.message
  if (event.type === "volume") {
    next.drives[message.uuid] = Object.assign({}, message)
    var label = driveLabel(message)
    var kind = message.known ? message.online ? "returned" : "gone" : "drive"
    next.toasts = next.toasts.filter(function(toast) {
      return !(toast.uuid === message.uuid && (toast.kind === kind || toast.kind === "drive"))
    })
    if (message.known || (message.online && next.ignored.indexOf(message.uuid) < 0)) {
      next.toasts.push({id: kind + ":" + message.uuid, kind: kind, uuid: message.uuid,
        title: kind === "drive" ? "New drive found" : label + (kind === "gone" ? " disconnected" : " connected"),
        body: kind === "drive" ? label + " (" + fsName(message.fs) + ", " + sizeText(message.size)
          + ") is connected. Scan it for photos, videos and documents to search?"
          : kind === "gone" ? "Its files stay searchable." : "Checking for changes",
        buttons: kind === "drive" ? [{label: "Not this drive", choice: "ignore"}, {label: "Scan", choice: "scan"}] : [],
        until: kind === "drive" ? null : event.now + 2900})
    }
    if (kind === "returned") {
      next.reconcile = {uuid: message.uuid, label: label, done: 0, total: 0, done_at: null}
    } else if (!message.online && next.reconcile && next.reconcile.uuid === message.uuid) {
      next.reconcile = null
    }
  } else if (event.type === "reconcile") {
    var previous = state.reconcile && state.reconcile.uuid === message.uuid ? state.reconcile : null
    var complete = message.done === message.total
    var doneAt = complete ? event.now : null
    if (complete) effects.push({type: "research"})
    next.reconcile = {uuid: message.uuid,
      label: message.label || (previous && previous.label) || driveLabel(next.drives[message.uuid] || {uuid: message.uuid}),
      done: message.done, total: message.total, done_at: doneAt}
  } else if (event.type === "paused") {
    next.disk = {free_gb: message.free_gb, need_gb: message.need_gb, error: message.error || null}
  } else if (event.type === "resumed") {
    next.disk = null
  } else if (event.type === "decide") {
    next.toasts = next.toasts.filter(function(toast) { return !(toast.kind === "drive" && toast.uuid === event.uuid) })
    effects.push({type: "send", message: {t: "drive_decision", uuid: event.uuid, choice: event.choice}})
    if (event.choice === "ignore") {
      if (next.ignored.indexOf(event.uuid) < 0) next.ignored.push(event.uuid)
      effects.push({type: "persist", changes: {ignoredVolumes: next.ignored.slice()}})
    } else if (event.choice === "scan") {
      effects.push({type: "summon", payload: {view: "drive", volume: event.uuid}})
    }
  } else if (event.type === "dismiss") {
    next.toasts = next.toasts.filter(function(toast) { return toast.id !== event.id })
  } else if (event.type === "tick") {
    next.toasts = next.toasts.filter(function(toast) { return toast.until === null || toast.until > event.now })
  } else if (event.type === "settings") {
    next.ignored = event.ignoredVolumes.slice()
    next.toasts = next.toasts.filter(function(toast) {
      return toast.kind !== "drive" || next.ignored.indexOf(toast.uuid) < 0
    })
  }
  return {state: next, effects: effects}
}

function fsName(fs) {
  var names = {exfat: "exFAT", vfat: "FAT32", ntfs: "NTFS", ext4: "ext4", btrfs: "Btrfs"}
  return Object.prototype.hasOwnProperty.call(names, fs) ? names[fs] : fs
}

function sizeText(bytes) {
  var unit = bytes >= 1e12 ? "TB" : bytes >= 1e9 ? "GB" : "MB"
  var value = bytes / (unit === "TB" ? 1e12 : unit === "GB" ? 1e9 : 1e6)
  return value.toFixed(value < 100 ? 1 : 0) + " " + unit
}

function driveLabel(volume) {
  var mount = (volume.mount || "").replace(/\/+$/, "")
  return volume.label || mount.slice(mount.lastIndexOf("/") + 1) || volume.uuid
}

function footer(state, now) {
  var rec = state.reconcile
  if (!rec || (rec.done_at !== null && now >= rec.done_at + 1250)) return null
  return {text: rec.done_at !== null ? rec.label + " is up to date" : "Checking " + rec.label + " for changes",
    fraction: rec.done_at !== null ? 1 : rec.total ? rec.done / rec.total : 0}
}

// The daemon's disk-low error, with the free and needed space as fact tokens.
function diskBanner(state) {
  if (!state.disk) return null
  return {error: state.disk.error,
    tokens: [{k: "free", v: state.disk.free_gb + " GB"}, {k: "needed", v: state.disk.need_gb + " GB"}]}
}

function indexedToken(files) {
  return {k: "indexed", v: F.count(files)}
}

function freshKeys(prevItems, nextItems, prevFiles, nextFiles) {
  var limit = nextFiles - prevFiles
  var fresh = []
  var previous = prevItems.map(function(item) { return item.id })
  for (var i = 0; i < nextItems.length && fresh.length < limit; i++) {
    var key = nextItems[i].id
    if (previous.indexOf(key) < 0 && fresh.indexOf(key) < 0) fresh.push(key)
  }
  return fresh
}

function driveFacts(volume, scan) {
  var scanText = scan && scan.running ? "running" : scan && scan.seconds != null ? scan.seconds.toFixed(1) + " s" : "—"
  return [{k: "mount", v: volume.mount || "—"}, {k: "fs", v: volume.fs}, {k: "scan", v: scanText},
    {k: "index", v: "internal disk"}, {k: "offline", v: "results kept"}]
}

function relPath(abs, mount) {
  var base = (mount || "").replace(/\/+$/, "")
  return base && (abs === base || abs.indexOf(base + "/") === 0) ? abs.slice(base.length) || "/" : abs
}

function dialogFooter(progress, uuid, label) {
  var volume = progress && progress.volumes && progress.volumes[uuid]
  var done = volume ? volume.done : 0
  var total = volume ? volume.total : 0
  // The child reports 0 of 0 for a drive while it is still crawling.
  var complete = !!volume && done === total && (total > 0 || !(progress && progress.running))
  return {text: (complete ? "Indexed " : "Indexing ") + (label || (volume && volume.label) || uuid),
    count: F.count(done) + " of " + F.count(total), fraction: total ? done / total : complete ? 1 : 0, done: complete}
}
