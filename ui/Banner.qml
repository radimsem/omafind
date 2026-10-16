import QtQuick

// `.ban` as an ErrorCard in the yellow tone: a bold lead, optional fact tokens (the disk banner),
// the sentence and a Retry button. An empty action hides the button.
ErrorCard {
  id: root

  property string lead: ""
  property string text: ""
  property string action: "Retry"

  signal triggered()

  tone: "warn"
  retryHere: true
  retryText: action
  error: lead !== "" || text !== ""
    ? ({code: "", title: lead, detail: text, fix: action !== "" ? {kind: "retry"} : null})
    : null
  onRetry: root.triggered()
}
