import QtQuick
import qs.Commons
import ".." as Plugin
import "../lib/setup.js" as Setup
import "../lib/errors.js" as Errors
import "../lib/keycombo.js" as Keycombo

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

  readonly property var progress: service ? service.progress : null
  readonly property var rates: service && service.discover ? service.discover.rates : null
  readonly property var head: Setup.indexHead(progress, rates)
  readonly property var problems: progress && progress.problems ? progress.problems : []
  readonly property var indexError: service ? service.indexError : null
  readonly property var toolErrors: progress && Array.isArray(progress.tool_errors) ? progress.tool_errors : []
  // The problem list (up to eight rows) and the error cards grow the panel instead of scrolling inside it.
  readonly property real extraHeight: (showList && problems.length ? list.height + Style.space(8) : 0)
    + kinds.extraHeight
    + (cards.visible ? cards.height + Plugin.Tokens.setupGap : 0)
    + (bindsCard.visible ? bindsCard.height + Plugin.Tokens.setupGap : 0)
    + (saveCard.visible ? saveCard.height + Plugin.Tokens.setupGap : 0)
  readonly property var bindMap: service ? Keycombo.bindMap(service.binds) : ({})
  readonly property bool bindsKnown: !!service && (service.bindsReady || !!service.bindsError)
  readonly property var chosenParts: Keycombo.fromHyprland(chosen)
  // The saved chord may be taken by a bind added since; the user must pick another first. A
  // saved chord the recorder cannot spell is shown raw and not checked.
  readonly property string chosenConflict: service && service.bindsReady && chosenParts.length
    ? Keycombo.bindConflict(chosenParts, bindMap) || "" : ""

  function begin() {
    saveError = ""
    chosen = service ? service.settings.shortcut : "SUPER + E"
    if (service) service.getBinds()
  }

  function stop() {
    recorder.stop()
  }

  function focusFirst() {
    if (save.enabled) save.forceActiveFocus()
    else closeButton.forceActiveFocus()
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

  // Retry on the index card starts the saved roots again.
  function retryIndex() {
    if (service) service.startIndexing(service.settings.roots, service.settings.codeRoots)
  }

  Column {
    width: parent.width
    spacing: Plugin.Tokens.setupGap

    Column {
      width: parent.width
      spacing: Style.space(10)

      Item {
        width: parent.width
        height: countText.implicitHeight

        Label {
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

    KindProgress {
      id: kinds
      width: parent.width
      topPadding: Style.space(2)
      progress: root.progress
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
            tokens: Setup.problemTokens(modelData, root.service && root.service.discover ? root.service.discover.home : "")
          }
        }
      }
    }

    Column {
      id: cards
      visible: !!root.indexError || root.toolErrors.length > 0
      width: parent.width
      spacing: Style.space(8)

      ErrorCard {
        objectName: "omafindIndexError"
        width: parent.width
        error: root.indexError
        visible: !!error
        retryHere: true
        onRetry: root.retryIndex()
      }

      // A count model keeps each card, and its install polling, alive across progress updates.
      Repeater {
        model: root.toolErrors.length

        delegate: ErrorCard {
          required property int index
          objectName: "omafindToolError"
          width: cards.width
          error: root.toolErrors[index] || null
          onRetry: if (root.service) root.service.retryFailed("tool-missing")
        }
      }
    }

    Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }

    Column {
      width: parent.width
      spacing: Style.space(4)

      Label {
        text: "Open omafind from anywhere"
        textFormat: Text.PlainText
        color: Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.subtitle
        font.bold: true
      }

      Label {
        width: parent.width
        wrapMode: Text.Wrap
        text: "omafind writes its own block in your Hyprland bindings and reloads Hyprland. Nothing else in your config changes."
        textFormat: Text.PlainText
        color: Plugin.Tokens.dim
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }
    }

    ShortcutRow {
      id: shortcutRow
      width: parent.width
      parts: root.chosenParts.length ? root.chosenParts : root.chosen !== "" ? [root.chosen] : []
      recording: recorder.active
      canChange: !!root.service && root.service.bindsReady
      note: recorder.conflict
        || (recorder.lost ? "Hyprland left recording mode, so omafind stopped recording. Press Change to try again." : "")
        || (recorder.exposed ? "Hyprland could not enter recording mode. Press Change to try again." : "")
        || root.chosenConflict
      noteTone: note !== "" ? "warn" : ""
      onChange: {
        recorder.start()
        shortcutRow.take()
      }
      onCancel: recorder.stop()
      onCaptured: (key, modifiers) => recorder.capture(key, modifiers)
    }

    ErrorCard {
      id: bindsCard
      objectName: "omafindBindsError"
      width: parent.width
      error: root.service ? root.service.bindsError : null
      visible: !!error
      retryHere: true
      onRetry: {
        if (!root.service) return
        if (root.service.bindsError && root.service.bindsError.code === "daemon-offline") root.service.installHelper()
        else root.service.getBinds()
      }
    }

    ShortcutRecorder {
      id: recorder
      binds: root.bindMap
      onRecorded: chord => root.chosen = chord
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

        Label {
          text: "Add \"Find files\" to the Omarchy menu"
          textFormat: Text.PlainText
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }

        Label {
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

    ErrorCard {
      id: saveCard
      objectName: "omafindSaveError"
      width: parent.width
      error: Errors.wrap(root.saveError)
      visible: !!error
    }

    Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }

    Item {
      width: parent.width
      height: Style.space(32)

      Label {
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
          onClicked: {
            recorder.stop()
            root.closeRequested()
          }
        }

        ActionButton {
          id: save
          objectName: "omafindSetupSave"
          text: "Save shortcut and open search"
          primary: true
          neutral: true
          focusable: true
          enabled: root.chosen !== "" && root.bindsKnown && root.chosenConflict === "" && !recorder.active && recorder.operation === "" && !recorder.pendingLeave && !root.saving
          onClicked: root.saveShortcut()
        }
      }
    }
  }
}
