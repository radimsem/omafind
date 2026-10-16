# omafind

omafind is an Omarchy 4 plugin (QML on Quickshell) with a Python daemon, `omafindd`, that searches local files by content through one embedding model run by a stock `llama-server`. Work arrives as GitHub issues #1 to #6. Each issue carries its plan, its verification list and its blockers.

- Read the issue in full before writing code. The spec is `docs/spec.md`; ADR-4 (`docs/adr/0004-stock-llama-server.md`) holds the Phase 0 numbers.
- `docs/ipc.md` owns the socket messages. When your issue adds a message or a settings key, update it, `settings.example.json`, `settings.py`, `lib/Settings.js` and the README table in the same pull request.
- Read `docs/DESIGN.md` before touching any QML surface.

## The machine you run on

You work on the owner's live Omarchy desktop (32 GB RAM, zram swap in RAM, RTX 3060). Agent sessions run together in `herdr.slice`, which has `MemoryHigh=22G` and is not watched by systemd-oomd. One runaway process there does not get killed: the kernel throttles the whole slice into swap and every agent freezes until the owner reboots.

That happened on 2026-10-12. `scripts/build-runtime.sh` ran `cmake --build -j $(nproc)`. Each llama.cpp `vulkan-shaders-gen` job starts `min(16, CPUs)` `glslc` compilers of its own, so ninja's 12 jobs ran about 144 `glslc` at once, next to a torch job. The session stalled for 1.5 hours with no OOM kill.

- Run every heavy job inside its own memory cap with no swap, so the kernel kills it instead of freezing the session:
  ```bash
  systemd-run --user --scope --quiet --collect -p MemoryMax=8G -p MemorySwapMax=0 -- <command>
  ```
  Heavy means a runtime build, `llama-server`, `scripts/probe.py`, the manual parity test, torch or sentence-transformers, and model downloads with verification. `scripts/build-runtime.sh` caps itself at 12 GiB (`OMAFIND_BUILD_MEMORY_MAX`), generates shaders one generator at a time and sizes `-j` to the cap.
- Run one heavy job at a time. Never start a build, a server and a torch job in parallel, and never fan out parallel agents that each start one.
- Stop every `llama-server` you start. `pgrep -x llama-server` must be empty when you finish.
- The unit tests are light (`uv run --project helper pytest`, under 2 s) and need no cap. The manual suite and the probe do; the commands in the README already carry it.
- While a heavy job runs, watch its scope (`systemctl --user show <scope> -p MemoryPeak`) rather than waiting blind.
- `/tmp` is tmpfs. Anything you keep there, such as reference vectors or logs, is lost on a reboot, so copy results into the repo or `~/.local/share/omafind/cache` as soon as they exist.
- The dev venv at `helper/.venv` holds a symlink, so `omarchy plugin validate .` fails in a dev checkout. Validate a clean clone.
- Do not edit `~/.config/omarchy/shell.json` by hand. If a check needs a settings write, back the file up, use the shell API and restore the backup afterwards.
