import QtQuick
import QtMultimedia
import Quickshell
import qs.Commons
import ".." as Plugin
import "../lib/format.js" as Format
import "../lib/keys.js" as KeyMap
import "../lib/searchState.js" as SearchState

// One result in the right pane: media by kind, name, folder, meta, why line and actions.
// PreviewPane keeps two of these and cross-fades between them.
Item {
  id: root

  property var item: null
  property var preview: null
  property bool shown: false
  property var player: null
  property var markers: []
  property string editorName: "Neovim"
  // "acc" or "sec" while the 260 ms press shows before the overlay closes.
  property string flash: ""
  readonly property alias videoOutput: videoOut

  signal primaryClicked()
  signal secondaryClicked()
  signal playClicked()

  readonly property var entry: item || ({})
  readonly property string kind: entry.kind || ""
  readonly property bool offline: entry.offline === true
  readonly property real total: entry.info && entry.info.duration ? entry.info.duration : 0
  readonly property bool mine: !!player && player.started && player.playback.id === entry.id
  readonly property real playhead: mine ? player.position : (entry.loc || 0)
  readonly property bool playingHere: mine && player.playing
  // The daemon's preview picks the line the opener jumps to; actions name that line.
  readonly property var jump: preview && (kind === "text" || kind === "code") ? preview.jump : null
  readonly property string imageSource: {
    var path = preview && preview.image ? preview.image : entry.thumb || (kind === "image" ? entry.path : "")
    return path ? Util.fileUrl(path) : ""
  }

  function folder(value) {
    var dir = value.dir || ""
    var home = Quickshell.env("HOME") || ""
    if ((value.offline || value.drive) && value.label) return value.label + " · " + dir
    if (home && (dir === home || dir.indexOf(home + "/") === 0)) return "~" + dir.slice(home.length)
    return dir
  }

  function fraction(seconds) {
    return total > 0 ? Math.max(0, Math.min(1, seconds / total)) : 0
  }

  opacity: shown ? 1 : 0
  visible: opacity > 0
  Behavior on opacity { NumberAnimation { duration: 120 } }

  Item {
    id: media
    anchors.top: parent.top
    anchors.topMargin: Style.space(26)
    anchors.left: parent.left
    anchors.right: parent.right
    height: Plugin.Tokens.mediaHeight
    transform: Translate {
      y: root.shown ? 0 : Style.space(6)
      Behavior on y { NumberAnimation { duration: root.shown ? 160 : 0; easing.type: Easing.BezierSpline; easing.bezierCurve: Plugin.Tokens.ease } }
    }

    // Image, a video frame, or a cached thumbnail of an offline file.
    Rectangle {
      id: picture
      anchors.centerIn: parent
      visible: root.offline || root.kind === "image" || root.kind === "video"
      width: Style.space(600)
      height: Style.space(400)
      radius: Style.cornerRadius
      color: Plugin.Tokens.surface0
      clip: true

      Icon {
        anchors.centerIn: parent
        visible: frame.status !== Image.Ready && root.kind !== "video"
        name: "image"
        size: Style.space(40)
        strokeWidth: 1.1
        color: Plugin.Tokens.dim
        opacity: root.offline ? 0.5 : 1
      }

      Image {
        id: frame
        anchors.fill: parent
        source: root.imageSource
        fillMode: Image.PreserveAspectFit
        asynchronous: true
        opacity: root.offline ? 0.5 : 1
      }

      VideoOutput {
        id: videoOut
        anchors.fill: parent
        visible: root.kind === "video" && root.mine
        fillMode: VideoOutput.PreserveAspectFit
      }

      Rectangle {
        visible: root.offline
        x: Style.space(10)
        y: Style.space(10)
        width: offlineText.implicitWidth + 2 * Style.space(7)
        height: Style.space(22)
        radius: Style.cornerRadius
        color: Plugin.Tokens.chip

        Text {
          id: offlineText
          anchors.centerIn: parent
          text: "offline"
          textFormat: Text.PlainText
          color: Plugin.Palette.yellow
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          font.bold: true
        }
      }

      Item {
        anchors.fill: parent
        visible: root.kind === "video" && !root.offline

        Rectangle {
          anchors.centerIn: parent
          width: Style.space(60)
          height: width
          radius: width / 2
          color: Util.alpha(Color.background, 0.78)
          border.width: 2
          border.color: Color.foreground

          Icon {
            anchors.centerIn: parent
            anchors.horizontalCenterOffset: root.playingHere ? 0 : Style.space(1.5)
            name: root.playingHere ? "pause" : "play"
            filled: true
            size: Style.space(24)
            color: Color.foreground
          }

          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: root.playClicked()
          }
        }

        Rectangle {
          x: Style.space(12)
          anchors.bottom: parent.bottom
          anchors.bottomMargin: Style.space(34)
          width: chipText.implicitWidth + 2 * Style.space(7)
          height: Style.space(22)
          radius: Style.cornerRadius
          color: Plugin.Tokens.chip

          Text {
            id: chipText
            anchors.centerIn: parent
            text: root.mine ? Format.duration(root.playhead) + " / " + Format.duration(root.total)
              : (Format.at(root.entry) || "")
            textFormat: Text.PlainText
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            font.bold: true
          }
        }

        Rectangle {
          id: scrub
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.leftMargin: Style.space(12)
          anchors.rightMargin: Style.space(12)
          anchors.bottom: parent.bottom
          anchors.bottomMargin: Style.space(16)
          height: Style.space(8)
          color: Util.alpha(Color.foreground, 0.22)

          Rectangle {
            height: parent.height
            width: parent.width * root.fraction(root.playhead)
            color: Util.alpha(Color.foreground, 0.5)
            Behavior on width { NumberAnimation { duration: 100; easing.type: Easing.Linear } }
          }

          Repeater {
            model: root.markers
            delegate: Rectangle {
              required property var modelData
              x: scrub.width * modelData - width / 2
              y: -Style.space(3)
              width: Style.space(3)
              height: Style.space(14)
              color: Color.accent
            }
          }

          Rectangle {
            z: 1
            x: scrub.width * root.fraction(root.entry.loc || 0) - width / 2
            y: -Style.space(5)
            width: Style.space(4)
            height: Style.space(18)
            color: Plugin.Palette.yellow
          }

          Rectangle {
            visible: root.mine
            x: scrub.width * root.fraction(root.playhead) - 1
            y: -Style.space(4)
            width: 2
            height: Style.space(16)
            color: Color.foreground
            Behavior on x { NumberAnimation { duration: 100; easing.type: Easing.Linear } }
          }
        }
      }
    }

    // `.pcard`: waveform with the matched window, play button, track and caption.
    Rectangle {
      id: card
      anchors.centerIn: parent
      visible: root.kind === "audio" && !root.offline
      width: Style.space(600)
      height: Style.space(340)
      radius: Style.cornerRadius
      color: Plugin.Tokens.surface0

      readonly property var bars: root.preview && root.preview.bars ? root.preview.bars : []
      readonly property int first: Math.floor(root.fraction(root.entry.loc || 0) * 64)
      readonly property int last: Math.max(first, Math.ceil(root.fraction(root.entry.loc_end || root.entry.loc || 0) * 64) - 1)
      readonly property real headIndex: root.fraction(root.playhead) * 64

      Item {
        id: wave
        x: Style.space(28)
        y: Style.space(26)
        width: parent.width - 2 * Style.space(28)
        height: Style.space(150)

        Repeater {
          model: card.bars.length ? card.bars.length : 0
          delegate: Rectangle {
            id: bar
            required property int index
            readonly property bool inWindow: index >= card.first && index <= card.last
            readonly property bool played: root.mine && inWindow && index < card.headIndex
            x: card.bars.length > 1 ? index * (wave.width - width) / (card.bars.length - 1) : 0
            anchors.verticalCenter: parent.verticalCenter
            width: Style.space(5)
            height: Math.max(2, wave.height * Math.min(100, card.bars[index]) / 100)
            color: played ? Color.foreground : inWindow ? Color.accent : Plugin.Tokens.dim
            Behavior on color { ColorAnimation { duration: 100; easing.type: Easing.Linear } }
            transform: Scale {
              id: pulse
              origin.y: bar.height / 2
              yScale: 1
            }
            SequentialAnimation {
              running: bar.inWindow && root.playingHere
              loops: Animation.Infinite
              onRunningChanged: if (!running) pulse.yScale = 1
              NumberAnimation { target: pulse; property: "yScale"; to: 0.8; duration: 640; easing.type: Easing.InOutQuad }
              NumberAnimation { target: pulse; property: "yScale"; to: 1; duration: 640; easing.type: Easing.InOutQuad }
            }
          }
        }

        Rectangle {
          visible: root.mine
          x: wave.width * card.headIndex / 64 - 1
          y: Style.space(6)
          width: 2
          height: parent.height - 2 * Style.space(6)
          color: Color.foreground
          Behavior on x { NumberAnimation { duration: 100; easing.type: Easing.Linear } }
        }
      }

      Item {
        id: controls
        anchors.top: wave.bottom
        anchors.topMargin: Style.space(22)
        anchors.left: wave.left
        anchors.right: wave.right
        height: Style.space(46)

        Rectangle {
          id: playButton
          width: Style.space(46)
          height: width
          radius: width / 2
          color: Color.accent

          Icon {
            anchors.centerIn: parent
            anchors.horizontalCenterOffset: root.playingHere ? 0 : Style.space(1.5)
            name: root.playingHere ? "pause" : "play"
            filled: true
            size: Style.space(20)
            color: Color.background
          }

          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: root.playClicked()
          }
        }

        Rectangle {
          id: track
          anchors.left: playButton.right
          anchors.leftMargin: Style.space(18)
          anchors.right: time.visible ? time.left : parent.right
          anchors.rightMargin: time.visible ? Style.space(18) : 0
          anchors.verticalCenter: parent.verticalCenter
          height: Style.space(6)
          color: Style.hoverFill

          Rectangle {
            height: parent.height
            width: parent.width * root.fraction(root.playhead)
            color: Util.alpha(Color.foreground, 0.25)
            Behavior on width { NumberAnimation { duration: 100; easing.type: Easing.Linear } }
          }

          Rectangle {
            x: parent.width * root.fraction(root.entry.loc || 0)
            y: -Style.space(3)
            width: Math.max(Style.space(4), parent.width * (root.fraction(root.entry.loc_end || 0) - root.fraction(root.entry.loc || 0)))
            height: Style.space(12)
            color: Color.accent
          }
        }

        Text {
          id: time
          visible: root.mine
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          width: Math.max(Style.space(40), implicitWidth)
          horizontalAlignment: Text.AlignRight
          text: Format.duration(root.playhead)
          textFormat: Text.PlainText
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          font.bold: true
        }
      }

      Text {
        anchors.top: controls.bottom
        anchors.topMargin: Style.space(22)
        anchors.horizontalCenter: parent.horizontalCenter
        text: root.total > 0 && root.entry.loc != null
          ? Format.windowCaption(root.entry.loc, root.entry.loc_end || root.entry.loc, root.total) : ""
        textFormat: Text.PlainText
        color: Plugin.Tokens.fg2
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }
    }

    // The rendered PDF page.
    Rectangle {
      anchors.centerIn: parent
      visible: root.kind === "pdf" && !root.offline
      width: Style.space(330)
      height: Style.space(410)
      radius: Style.cornerRadius
      color: Color.popups.background
      clip: true

      Image {
        anchors.fill: parent
        source: root.kind === "pdf" ? root.imageSource : ""
        fillMode: Image.PreserveAspectFit
        asynchronous: true
      }

      Rectangle {
        x: Style.space(12)
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Style.space(12)
        width: pageText.implicitWidth + 2 * Style.space(8)
        height: Style.space(22)
        radius: Style.cornerRadius
        color: Plugin.Tokens.chip

        Text {
          id: pageText
          anchors.centerIn: parent
          text: Format.at(root.entry) || ""
          textFormat: Text.PlainText
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          font.bold: true
        }
      }
    }

    // `.pv-text`: excerpt with line numbers, hit lines and the hit words.
    Rectangle {
      id: well
      anchors.centerIn: parent
      visible: (root.kind === "text" || root.kind === "code") && !root.offline
      width: Style.space(640)
      height: Style.space(400)
      radius: Style.cornerRadius
      color: Plugin.Tokens.well
      border.width: 1
      border.color: Plugin.Tokens.sep
      clip: true

      readonly property var lines: root.preview && root.preview.lines ? root.preview.lines : []
      readonly property int lineHeight: Style.space(20)
      readonly property int fits: Math.floor((height - 2 * Style.space(14)) / lineHeight)
      readonly property int start: {
        if (lines.length <= fits || !root.preview) return 0
        for (var i = 0; i < lines.length; i++)
          if (lines[i].no === root.preview.jump) return Math.max(0, Math.min(i - Math.floor(fits / 2), lines.length - fits))
        return 0
      }
      readonly property color hitLine: Qt.tint(color, Util.alpha(Color.accent, 0.10))

      function markup(line) {
        var runs = SearchState.highlight(line.text, root.entry.hits || [], "")
        var base = line.hit ? hitLine : color
        var mark = Qt.tint(base, Util.alpha(Plugin.Palette.yellow, 0.18))
        var out = ""
        for (var i = 0; i < runs.length; i++) {
          var text = runs[i].t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/\t/g, "    ").replace(/ /g, "&nbsp;")
          out += runs[i].m ? "<span style=\"background-color:" + mark + ";color:" + Plugin.Palette.yellow + "\">"
            + text + "</span>" : text
        }
        return out || "&nbsp;"
      }

      Column {
        y: Style.space(14)
        width: parent.width

        Repeater {
          model: well.lines.slice(well.start, well.start + well.fits + 1)

          delegate: Rectangle {
            required property var modelData
            width: well.width
            height: well.lineHeight
            color: modelData.hit ? well.hitLine : "transparent"

            Text {
              id: number
              width: Style.space(48)
              rightPadding: Style.space(14)
              anchors.verticalCenter: parent.verticalCenter
              horizontalAlignment: Text.AlignRight
              text: modelData.no
              textFormat: Text.PlainText
              color: Color.muted
              font.family: Style.font.family
              font.pixelSize: Style.font.body
            }

            Text {
              anchors.left: number.right
              anchors.right: parent.right
              anchors.rightMargin: Style.space(14)
              anchors.verticalCenter: parent.verticalCenter
              text: well.markup(modelData)
              textFormat: Text.RichText
              elide: Text.ElideRight
              color: Plugin.Tokens.fg2
              font.family: Style.font.family
              font.pixelSize: Style.font.body
            }
          }
        }
      }

      Rectangle {
        visible: !!(root.preview && root.preview.range)
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: Style.space(10)
        width: rangeText.implicitWidth + 2 * Style.space(8)
        height: Style.space(22)
        radius: Style.cornerRadius
        color: Util.alpha(Color.background, 0.9)
        border.width: 1
        border.color: Plugin.Tokens.sep

        Text {
          id: rangeText
          anchors.centerIn: parent
          text: root.preview && root.preview.range ? "lines " + root.preview.range[0] + "–" + root.preview.range[1] : ""
          textFormat: Text.PlainText
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          font.bold: true
        }
      }
    }
  }

  Column {
    id: info
    anchors.top: media.bottom
    anchors.topMargin: Style.space(18)
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.leftMargin: Style.space(32)
    anchors.rightMargin: Style.space(32)
    spacing: Style.space(18)

    Column {
      width: parent.width
      spacing: Style.space(6)

      Text {
        width: parent.width
        text: root.entry.name || ""
        textFormat: Text.PlainText
        elide: Text.ElideMiddle
        color: Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.iconLarge
        font.bold: true
      }

      Text {
        width: parent.width
        text: root.folder(root.entry)
        textFormat: Text.PlainText
        elide: Text.ElideMiddle
        color: Plugin.Tokens.fg2
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }

      Text {
        width: parent.width
        text: root.item ? Format.meta(root.entry) : ""
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: Plugin.Tokens.dim
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }
    }

    WhyLine {
      width: parent.width
      item: root.entry
    }
  }

  Row {
    anchors.left: parent.left
    anchors.leftMargin: Style.space(32)
    anchors.bottom: parent.bottom
    anchors.bottomMargin: Style.space(24)
    spacing: Style.space(8)

    ActionButton {
      primary: true
      enabled: !root.offline
      flash: root.flash === "acc"
      text: KeyMap.actionLabel(root.entry, root.editorName, root.jump)
      onClicked: root.primaryClicked()
    }

    ActionButton {
      flash: root.flash === "sec"
      text: root.offline ? "Copy path" : "Show in folder"
      onClicked: root.secondaryClicked()
    }

    Facts {
      anchors.verticalCenter: parent.verticalCenter
      leftPadding: Style.space(6)
      visible: !root.offline && !!(root.preview && root.preview.opener)
        && ["video", "pdf", "text", "code"].indexOf(root.kind) >= 0
      tokens: root.preview && root.preview.opener ? [{k: "opener", v: root.preview.opener, tone: "plain"}] : []
      fontSize: Style.font.bodySmall
    }
  }
}
