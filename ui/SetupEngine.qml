import QtQuick
import qs.Commons
import ".." as Plugin
import "../lib/setup.js" as Setup

// Step 1 (board Setup, M3 step 1): helper, embedding server and model, then the footer buttons.
FocusScope {
  id: root

  property var service: null

  signal nextRequested()

  readonly property var rp: service ? service.runtimeProgress : null
  readonly property bool helperReady: !!service && service.ready
  readonly property var helper: Setup.helperTask({ready: helperReady,
    unit: service ? service.connection.unit : "unknown",
    socket: service ? service.connection.socket : "closed",
    failures: service ? service.connection.failures : 0})
  readonly property var server: Setup.serverTask(rp)
  readonly property var model: Setup.modelTask(rp)
  readonly property var engine: Setup.engineButton(rp, helperReady)
  readonly property bool ready: Setup.engineReady(rp)

  function focusFirst() {
    // With no ready control the scope takes focus, so no ring shows until Tab.
    if (helperTask.buttonText !== "" && helperTask.buttonEnabled) helperTask.forceActiveFocus()
    else if (next.enabled) next.forceActiveFocus()
    else root.forceActiveFocus()
  }

  Column {
    id: column
    width: parent.width
    spacing: Plugin.Tokens.setupGap

    TaskRow {
      id: helperTask
      width: parent.width
      mark: root.service && root.service.helperRunning ? "run" : root.helper.mark
      title: "Helper"
      tokens: root.helper.tokens
      value: root.helper.value || ""
      valueTone: root.helper.mark === "ok" ? "ok" : "plain"
      buttonText: root.helper.install ? "Install" : ""
      buttonEnabled: !!root.service && !root.service.helperRunning
      onButtonClicked: root.service.installHelper()
    }

    Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }

    TaskRow {
      width: parent.width
      mark: root.server.mark
      title: "Embedding server"
      tokens: root.server.tokens
      value: root.server.value || ""
      valueTone: root.server.valueTone
    }

    Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }

    Column {
      width: parent.width
      spacing: Style.space(10)

      TaskRow {
        width: parent.width
        mark: root.model.mark
        title: "EmbeddingGemma 2 model"
        tokens: root.model.tokens
        value: root.model.value || ""
        valueTone: root.model.valueTone
        valueTokens: root.model.got
      }

      ProgressBar {
        x: Style.space(34)
        width: parent.width - x
        height: Style.space(6)
        fraction: Setup.totalFraction(root.rp)
        done: root.ready
      }

      // The board's file lines: plain text rows 4 px apart, no bar of their own.
      Column {
        x: Style.space(34)
        width: parent.width - x
        spacing: Style.space(4)

        Repeater {
          model: Setup.fileLines(root.rp)

          delegate: Item {
            required property var modelData
            width: parent.width
            height: name.implicitHeight

            Row {
              spacing: Style.space(8)

              Text {
                width: Style.space(10)
                horizontalAlignment: Text.AlignHCenter
                text: modelData.icon
                textFormat: Text.PlainText
                color: modelData.tone === "ok" ? Plugin.Palette.green
                  : modelData.tone === "accent" ? Color.accent
                  : Plugin.Tokens.dim
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
              }

              Text {
                id: name
                text: modelData.name
                textFormat: Text.PlainText
                color: Color.foreground
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
              }
            }

            Text {
              anchors.right: parent.right
              text: modelData.mb
              textFormat: Text.PlainText
              color: Plugin.Tokens.dim
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
            }
          }
        }
      }
    }

    Rectangle { width: parent.width; height: 1; color: Plugin.Tokens.sep }

    SetupFacts {
      width: Math.min(implicitWidth, parent.width)
      fontSize: Style.font.bodySmall
      tokens: [
        {k: "disk", v: "<b>~1.1 GB</b> model + server", tone: "plain"},
        {k: "vram indexing", v: "~1 GB", tone: "strong"},
        {k: "vram idle", v: "0", tone: "plain"}
      ]
    }
  }

  Item {
    anchors.bottom: parent.bottom
    width: parent.width
    height: Style.space(32)

    Text {
      anchors.left: parent.left
      anchors.right: buttons.left
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
      elide: Text.ElideRight
      text: Setup.engineHint(root.rp)
      textFormat: Text.PlainText
      color: root.rp && root.rp.state === "failed" ? Color.urgent : Plugin.Tokens.dim
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }

    Row {
      id: buttons
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(8)

      ActionButton {
        id: engineButton
        objectName: "omafindSetupEngineButton"
        visible: root.engine.visible
        enabled: root.engine.enabled
        text: root.engine.text
        focusable: true
        onClicked: {
          if (!root.service) return
          if (root.engine.action === "pause") root.service.runtimePause()
          else root.service.runtimeInstall()
        }
      }

      ActionButton {
        id: next
        objectName: "omafindSetupNext"
        primary: true
        neutral: true
        focusable: true
        enabled: root.ready
        text: "Next: pick folders"
        onClicked: root.nextRequested()
      }
    }
  }
}
