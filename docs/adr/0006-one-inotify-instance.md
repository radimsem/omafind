# ADR-6: One inotify instance for all watched folders

Status: accepted, 2026-10-15. Replaces the watchdog line of ADR-3.

## Context

The first watcher used watchdog, which opens one inotify instance and two threads for every watched directory.
On the owner's host the daemon held 932 inotify instances and 1,876 threads against `fs.inotify.max_user_instances = 1024`.
Directories past the limit went unwatched, and every other program of the user shares that limit.

## Decision

Watch every internal root through one inotify instance read by one thread, using `inotify_simple`.
Add one watch per allowed directory and drop the watch when the directory is removed or moved.
A queue overflow marks every root dirty so the next reconcile catches what was missed.
When the per-user watch limit is reached, stop adding watches for that pass, log one line with the number of unwatched directories and report it in the health facts.

## Consequences

The daemon uses one inotify instance however many folders the user picks.
`watchdog` leaves the dependencies; `inotify-simple` replaces it.
A host with a low `fs.inotify.max_user_watches` leaves some directories unwatched until the next reconcile.
