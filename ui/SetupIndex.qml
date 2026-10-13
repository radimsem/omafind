import QtQuick
import qs.Commons
import ".." as Plugin
import "../lib/setup.js" as Setup

// Step 3 (board Indexing, M3 step 5): first index progress, skips and the global shortcut.
FocusScope {
  id: root

  property var service: null
  property string chosen: ""
  property bool menuRow: true
  property bool showList: false
  property bool saving: false
  property string saveError: ""

  signal closeRequested()
  signal searchRequested()

  readonly property var chords: ["SUPER + E", "SUPER + D", "SUPER + U"]
  readonly property var progress: service ? service.progress : null
  readonly property var rates: service && service.discover ? service.discover.rates : null
  readonly property var head: Setup.indexHead(progress, rates)
  readonly property var checks: service ? service.bindingChecks : ({})
  readonly property var line: Setup.shortcutLine(checks, chosen)
  readonly property var problems: progress && progress.problems ? progress.problems : []
  // The problem list grows the panel instead of scrolling inside it, up to eight rows.
  readonly property real extraHeight: showList && problems.length ? list.height + Style.space(8) : 0

  function begin() {
    saveError = ""
    if (service) service.checkBindings(chords)
  }

  function focusFirst() {
    if (save.enabled) save.forceActiveFocus()
    else closeButton.forceActiveFocus()
  }

  function usable(chord) {
    return checks[chord] === "free" || checks[chord] === "ours"
  }

  // The configured shortcut when it is free or ours, else the first free one.
  function pick() {
    if (chosen !== "" && checks[chosen] !== undefined && checks[chosen] !== null) return
    var configured = service ? service.settings.shortcut : "SUPER + E"
    if (checks[configured] === undefined || checks[configured] === null) return
    if (usable(configured)) {
      chosen = configured
      return
    }
    for (var i = 0; i < chords.length; i++) {
      if (checks[chords[i]] === undefined || checks[chords[i]] === null) return
      if (usable(chords[i])) {
        chosen = chords[i]
        return
      }
    }
    chosen = configured
  }

  function saveShortcut() {
    if (!service || saving) return
    saving = true
    saveError = ""
    service.saveShortcut(chosen, menuRow, (ok, errorLine) => {
      root.saving = false
      if (ok) root.searchRequested()
      else root.saveError = errorLine || ""
    })
  }

  onChecksChanged: pick()

  Column {
    width: parent.width
    spacing: Plugin.Tokens.setupGap

    Column {
      width: parent.width
      spacing: Style.space(10)

      Item {
        width: parent.width
        height: countText.implicitHeight

        Text {
          id: countText
          text: root.head.count
          textFormat: Text.PlainText
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.display
          font.bold: true
        }

        SetupFacts {
          anchors.left: countText.right
          anchors.leftMargin: Style.space(10)
          anchors.baseline: countText.baseline
          tokens: root.head.facts
          fontSize: Style.font.body
        }

        Row {
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(6)

          Spinner {
            anchors.verticalCenter: parent.verticalCenter
            visible: root.head.spinning
            running: visible
          }

          SetupFacts {
            anchors.verticalCenter: parent.verticalCenter
            tokens: root.head.side
            fontSize: Style.font.bodySmall
          }
        }
      }

      ProgressBar {
        width: parent.width
        height: Style.space(6)
        fraction: root.head.fraction
        done: !!root.progress && !root.progress.running && root.head.fraction >= 1
      }
    }

    Column {
      width: parent.width
      topPadding: Style.space(2)
      spacing: Style.space(8)

      Repeater {
        model: Setup.kindRows(root.progress)

        delegate: Item {
          required property var modelData
          width: parent.width
          height: kindLabel.implicitHeight

          Text {
            id: kindLabel
            width: Style.space(80)
            text: modelData.label
            textFormat: Text.PlainText
            color: Plugin.Tokens.fg2
            font.family: Style.font.family
            font.pixelSize: Style.font.body
          }

          ProgressBar {
            x: Style.space(80) + Style.space(14)
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - x - Style.space(190) - Style.space(14)
            height: Style.space(6)
            fraction: modelData.fraction
            done: modelData.done
          }

          Text {
            anchors.right: parent.right
            width: Style.space(190)
            horizontalAlignment: Text.AlignRight
            text: modelData.text
            textFormat: Text.PlainText
            color: Plugin.Tokens.dim
            font.family: Style.font.family
            font.pixelSize: Style.font.body
          }
        }
      }
    }

    Item {
      width: parent.width
      height: Math.max(problemFacts.implicitHeight, showListButton.height)

      SetupFacts {
        id: problemFacts
        anchors.verticalCenter: parent.verticalCenter
        width: Math.min(implicitWidth, parent.width - showListButton.width - Style.space(8))
        tokens: Setup.problemFacts(root.progress)
        fontSize: Style.font.bodySmall
      }

      ActionButton {
        id: showListButton
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        visible: root.problems.length > 0
        text: "Show list"
        focusable: true
        buttonHeight: Style.space(24)
        fontSize: Style.font.bodySmall
        active: root.showList
        onClicked: root.showList = !root.showList
      }
    }

    Flickable {
      id: list
      visible: root.showList && root.problems.length > 0
      width: parent.width
      height: visible ? Math.min(problemColumn.implicitHeight, Style.space(8 * 18)) : 0
      contentHeight: problemColumn.implicitHeight
      clip: true
      boundsBehavior: Flickable.StopAtBounds

      Column {
        id: problemColumn
        width: list.width
        spacing: Style.space(4)

        Repeater {
          model: root.problems

          delegate: SetupFacts {
            required property var modelData
            width: Math.min(implicitWidth, problemColumn.width)
            fontSize: Style.font.bodySmall
            tokens: [
              {k: modelData.reason, v: Setup.displayPath(modelData.path, root.service && root.service.discover ? root.service.discover.home : ""), tone: "plain"}
            ]
          }
        }
      }
    }

    Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }

    Column {
      width: parent.width
      spacing: Style.space(4)

      Text {
        text: "Open omafind from anywhere"
        textFormat: Text.PlainText
        color: Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.subtitle
        font.bold: true
      }

      Text {
        width: parent.width
        wrapMode: Text.Wrap
        text: "omafind writes its own block in your Hyprland bindings and reloads Hyprland. Nothing else in your config changes."
        textFormat: Text.PlainText
        color: Plugin.Tokens.dim
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }
    }

    Item {
      width: parent.width
      height: Style.space(28)

      Row {
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(12)

        Row {
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(4)

          Repeater {
            model: root.chosen ? Setup.chordKeys(root.chosen) : []
            delegate: SetupKey {
              required property string modelData
              text: modelData
              implicitHeight: Style.space(26)
              fontSize: Style.font.body
              padding: Style.space(8)
            }
          }
        }

        Row {
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(6)

          Spinner {
            anchors.verticalCenter: parent.verticalCenter
            visible: root.line.tone === "busy"
            running: visible
          }

          Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: root.line.tone === "ok"
            text: "✓"
            textFormat: Text.PlainText
            color: Plugin.Palette.green
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
          }

          Text {
            anchors.verticalCenter: parent.verticalCenter
            text: root.line.tone === "busy" ? "Checking your bindings" : root.line.text
            textFormat: Text.PlainText
            color: root.line.tone === "warn" ? Plugin.Palette.yellow
              : root.line.tone === "busy" ? Plugin.Tokens.dim
              : Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
          }
        }
      }

      ActionButton {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        text: "Change"
        focusable: true
        buttonHeight: Style.space(28)
        enabled: root.line.tone !== "busy"
        onClicked: root.chosen = Setup.nextChord(root.checks, root.chosen)
      }
    }

    Row {
      spacing: Style.space(12)

      Switch {
        anchors.verticalCenter: parent.verticalCenter
        checked: root.menuRow
        label: "Add Find files to the Omarchy menu"
        onToggled: root.menuRow = !root.menuRow
      }

      Column {
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(2)

        Text {
          text: "Add \"Find files\" to the Omarchy menu"
          textFormat: Text.PlainText
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }

        Text {
          text: "One row in ~/.config/omarchy/extensions/omarchy-menu.jsonc"
          textFormat: Text.PlainText
          color: Plugin.Tokens.dim
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
        }
      }
    }
  }

  Column {
    anchors.bottom: parent.bottom
    width: parent.width
    spacing: Plugin.Tokens.setupGap

    Text {
      visible: root.saveError !== ""
      width: parent.width
      wrapMode: Text.Wrap
      text: root.saveError
      textFormat: Text.PlainText
      color: Color.urgent
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }

    Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }

    Item {
      width: parent.width
      height: Style.space(32)

      Text {
        anchors.left: parent.left
        anchors.right: buttons.left
        anchors.rightMargin: Style.space(8)
        anchors.verticalCenter: parent.verticalCenter
        elide: Text.ElideRight
        text: "Indexing keeps going after you close this. Progress shows in the search footer."
        textFormat: Text.PlainText
        color: Plugin.Tokens.dim
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }

      Row {
        id: buttons
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(8)

        ActionButton {
          id: closeButton
          objectName: "omafindSetupClose"
          text: "Close"
          focusable: true
          onClicked: root.closeRequested()
        }

        ActionButton {
          id: save
          objectName: "omafindSetupSave"
          text: "Save shortcut and open search"
          primary: true
          neutral: true
          focusable: true
          enabled: root.chosen !== "" && root.line.tone !== "busy" && root.line.tone !== "warn" && !root.saving
          onClicked: root.saveShortcut()
        }
      }
    }
  }
}
