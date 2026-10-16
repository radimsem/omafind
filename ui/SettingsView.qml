import QtQuick
import qs.Commons
import "." as Plugin
import "." as Parts
import "../lib/errors.js" as Errors
import "../lib/keycombo.js" as Keycombo
import "../lib/setup.js" as Setup

// Ctrl , from search: the shortcut, the "Find files" menu row and a way back to the Folders step.
FocusScope {
  id: root
  objectName: "omafindSettings"

  property var service: null
  property string chosen: ""
  property bool saving: false
  property bool saved: false
  property string saveError: ""
  property bool menuBusy: false
  property string menuError: ""

  signal backRequested()
  signal foldersRequested()

  readonly property real panelWidth: Style.space(760)
  readonly property real panelHeight: content.implicitHeight + 2 * Plugin.Tokens.setupPadding
  readonly property string current: service ? service.settings.shortcut : ""
  readonly property var bindMap: service ? Keycombo.bindMap(service.binds) : ({})
  readonly property bool bindsKnown: !!service && (service.bindsReady || !!service.bindsError)
  readonly property var chosenParts: Keycombo.fromHyprland(chosen)
  readonly property string chosenConflict: service && service.bindsReady && chosenParts.length
    ? Keycombo.bindConflict(chosenParts, bindMap) || "" : ""
  readonly property bool menuKnown: !!service && service.bindsReady && typeof service.menuRow === "boolean"
  readonly property int rootCount: service ? service.settings.roots.length : 0

  function reset() {
    saveError = ""
    menuError = ""
    saved = false
    chosen = service ? service.settings.shortcut : "SUPER + E"
    if (service) service.getBinds()
  }

  function stop() {
    recorder.stop()
  }

  function focusFirst() {
    shortcutRow.take()
  }

  function handleKey(event) {
    if (event.key !== Qt.Key_Escape) return
    stop()
    root.backRequested()
    event.accepted = true
  }

  function saveShortcut() {
    if (!service || saving) return
    saving = true
    saved = false
    saveError = ""
    service.saveShortcut(chosen, false, (ok, errorLine) => {
      root.saving = false
      if (ok) root.saved = true
      else root.saveError = errorLine || ""
    })
  }

  function toggleMenu() {
    if (!menuKnown || menuBusy) return
    menuBusy = true
    menuError = ""
    service.setMenuRow(!service.menuRow, (ok, errorLine) => {
      root.menuBusy = false
      if (!ok) root.menuError = errorLine || "The Omarchy menu could not be changed."
    })
  }

  Column {
    id: content
    x: Plugin.Tokens.setupPadding
    y: Plugin.Tokens.setupPadding
    width: parent.width - 2 * Plugin.Tokens.setupPadding
    spacing: Plugin.Tokens.setupGap

    Parts.SetupHeader {
      width: parent.width
      title: "Settings"
    }

    Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }

    Column {
      width: parent.width
      spacing: Style.space(4)

      Parts.Label {
        text: "Open omafind from anywhere"
        textFormat: Text.PlainText
        color: Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.subtitle
        font.bold: true
      }

      Parts.Label {
        width: parent.width
        wrapMode: Text.Wrap
        text: "omafind writes its own block in your Hyprland bindings and reloads Hyprland. Nothing else in your config changes."
        textFormat: Text.PlainText
        color: Plugin.Tokens.dim
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }
    }

    Parts.ShortcutRow {
      id: shortcutRow
      width: parent.width
      readonly property string warning: recorder.conflict
        || (recorder.lost ? "Hyprland left recording mode, so omafind stopped recording. Press Change to try again." : "")
        || (recorder.exposed ? "Hyprland could not enter recording mode. Press Change to try again." : "")
        || root.chosenConflict
      parts: root.chosenParts.length ? root.chosenParts : root.chosen !== "" ? [root.chosen] : []
      recording: recorder.active
      canChange: !!root.service && root.service.bindsReady
      note: shortcutRow.warning || (root.saved && root.chosen === root.current ? "saved" : "")
      noteTone: shortcutRow.warning !== "" ? "warn" : ""
      onChange: {
        recorder.start()
        shortcutRow.take()
      }
      onCancel: recorder.stop()
      onCaptured: (key, modifiers) => recorder.capture(key, modifiers)
    }

    Parts.ErrorCard {
      id: bindsCard
      objectName: "omafindSettingsBindsError"
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

    Parts.ShortcutRecorder {
      id: recorder
      binds: root.bindMap
      onRecorded: chord => {
        root.saved = false
        root.chosen = chord
      }
    }

    Row {
      spacing: Style.space(12)

      Parts.Switch {
        objectName: "omafindSettingsMenu"
        anchors.verticalCenter: parent.verticalCenter
        enabled: root.menuKnown && !root.menuBusy
        opacity: enabled ? 1 : 0.45
        checked: !!root.service && root.service.menuRow === true
        label: "Show Find files in the Omarchy menu"
        onToggled: root.toggleMenu()
      }

      Column {
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(2)

        Parts.Label {
          text: "Show \"Find files\" in the Omarchy menu"
          textFormat: Text.PlainText
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }

        Parts.Label {
          text: "One row in ~/.config/omarchy/extensions/omarchy-menu.jsonc"
          textFormat: Text.PlainText
          color: Plugin.Tokens.dim
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
        }
      }
    }

    Parts.ErrorCard {
      objectName: "omafindSettingsMenuError"
      width: parent.width
      error: Errors.wrap(root.menuError)
      visible: !!error
    }

    Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }

    Item {
      width: parent.width
      height: Style.space(32)

      Column {
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(2)

        Parts.Label {
          text: "Folders"
          textFormat: Text.PlainText
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }

        Parts.SetupFacts {
          tokens: [Setup.token("roots", Setup.count(root.rootCount))]
          fontSize: Style.font.bodySmall
        }
      }

      Parts.ActionButton {
        objectName: "omafindSettingsFolders"
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        text: "Change folders"
        focusable: true
        onClicked: {
          root.stop()
          root.foldersRequested()
        }
      }
    }

    Parts.ErrorCard {
      objectName: "omafindSettingsSaveError"
      width: parent.width
      error: Errors.wrap(root.saveError)
      visible: !!error
    }

    Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }

    Item {
      width: parent.width
      height: Style.space(32)

      Row {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(8)

        Parts.ActionButton {
          objectName: "omafindSettingsBack"
          text: "Back"
          focusable: true
          onClicked: {
            root.stop()
            root.backRequested()
          }
        }

        Parts.ActionButton {
          id: save
          objectName: "omafindSettingsSave"
          text: "Save shortcut"
          primary: true
          neutral: true
          focusable: true
          enabled: root.chosen !== "" && root.chosen !== root.current && root.bindsKnown && root.chosenConflict === "" && !recorder.active && recorder.operation === "" && !recorder.pendingLeave && !root.saving
          onClicked: root.saveShortcut()
        }
      }
    }
  }
}
