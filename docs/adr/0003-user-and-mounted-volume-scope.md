# ADR-3: User folders and mounted volumes

Status: accepted, 2026-10-13.

## Context

omafind searches the owner's selected folders and drives on an Omarchy desktop.
System-wide indexing would require broader access and expose other users' data to the index.
Removable drives can disappear or return at a different mount point.

## Decision

Limit indexing to selected folders in `$HOME` and mounted volumes that the user can read.
Run the daemon as the user. Use no root daemon and no fanotify.
Use watchdog inotify watches for internal roots and reconcile removable roots on mount.
Identify a volume by its filesystem UUID and files by their relative paths.
Store each drive's index and thumbnails on the internal disk.

## Consequences

Unreadable system files and other users' folders stay outside the scope.
Unplugged drives remain searchable through their cached index and thumbnails.
Reconciliation applies the same file and secrets rules as the initial crawl.
The daemon needs no elevated permissions or system-wide event stream.
