# UI socket

The daemon listens on `$XDG_RUNTIME_DIR/omafind/ui.sock`. The directory has mode 0700 and the socket has mode 0600. It checks `SO_PEERCRED` and closes a connection whose peer UID differs from its own.

Send one UTF-8 JSON object per line, terminated by `\n`. The line limit is 1 MiB (1,048,576 bytes), excluding the newline. An oversized or unterminated line closes the connection. Bad JSON and non-object JSON values are skipped. A supplied `v` must be the integer `1`; a version mismatch closes the connection. `hello` must include `v`.

`Service.qml` is the plugin's only socket client. It sends `hello` on every connect and reconnect. The CLI uses the same handshake for setup and status.

## Plugin to daemon

| t | Fields | Behavior |
|---|---|---|
| `hello` | `v:1` | Start the connection. Reply with the current `state` to this client. |

## Daemon to plugin

| t | Fields | Behavior |
|---|---|---|
| `state` | `v:1`, `runtime:"ready"\|"missing"`, `model:"ready"\|"missing"`, `embedder:"stopped"\|"text"\|"full"` | Reply to `hello`. The state shape and pushing a full state whenever a field changes are proposed. |

The scaffold implements the proposed state shape and push-on-change behavior. `runtime` checks for an executable runtime file. `model` checks that both pinned model files exist. `embedder` starts as `stopped`. Presence does not imply verified digests; `build-runtime` verifies them.

```json
{"t":"hello","v":1}
{"t":"state","v":1,"runtime":"missing","model":"missing","embedder":"stopped"}
```

Later issues append their messages here.
