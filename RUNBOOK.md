# Cursor Sub-Agent Runbook

## First-time setup

```shell
pip install -e ".[dev]"

# Linux/macOS
bash scripts/install-nats-server.sh
cargo build --release -p subagent-gateway --manifest-path bus/Cargo.toml

# Windows
powershell -ExecutionPolicy Bypass -File scripts/install-nats-server.ps1
cargo build --release -p subagent-gateway
```

Add credentials (pick one):

```shell
# Option A: repo-local (recommended for agents — pass --cwd to this repo)
# Create .env in repo root:
#   CURSOR_API_KEY=cursor_...

# Option B: machine-wide
# Create ~/.cursor/subagents/.env with CURSOR_API_KEY=cursor_...

# Option C: shell export (CI)
# export CURSOR_API_KEY=cursor_...
```

## Start stack

```shell
cursor-subagent bus start
cursor-subagent daemon start   # optional; spawn auto-starts daemon
cursor-subagent bus status --json
cursor-subagent daemon status --json
```

Linux startup is process-detached. After the commands exit, `nats-server`,
`subagent-gateway`, and `cursor-subagentd` should still be reachable through the
status commands.

Start or restart the daemon after the bus is running when you need `watch`:

```shell
cursor-subagent bus start
cursor-subagent daemon stop
cursor-subagent daemon start
```

## Smoke test (live Cursor)

```shell
cursor-subagent spawn \
  --task "Create scripts/hello_subagent.py: def main() prints 'Hello from subagent'" \
  --cwd . --json

python scripts/hello_subagent.py
cursor-subagent close <sessionId> --json
```

Expected script output: `Hello from subagent`

## Live watch and replay check

Use `--persist` when you want to verify event replay after close:

```shell
cursor-subagent spawn --persist \
  --task "Create tmp_cursor_subagent_watch.txt containing exactly: watch smoke start" \
  --cwd "$(pwd)" --json

cursor-subagent send <sessionId> \
  "Append a second line containing exactly: watch path ok" \
  --watch --json

cursor-subagent events <sessionId> --json
cursor-subagent close <sessionId> --json
```

Expected behavior:

- `send --watch --json` prints stream events and exits after `run_complete`.
- `events` returns stored SQLite events for persisted sessions.
- `close` returns `"purged": false` for persisted sessions and `"purged": true`
  for normal sessions.

## Agent delegation pattern

Main agents should:

1. `cursor-subagent bus start` (once per machine/session if not running)
2. `cursor-subagent spawn --task "..." --cwd /absolute/path/to/target/repo --json`
3. Parse JSON for `session_id`, `result`, `stream_url`
4. Optional: `cursor-subagent watch <sessionId>` from a second shell for live events
5. Follow-ups: `cursor-subagent send <sessionId> "..." --json` or `--watch --json`
6. Always: `cursor-subagent close <sessionId> --json`

Use one session per delegated task and reuse it with `send`; do not spawn a new
session for each follow-up.

## Troubleshooting

| Symptom | Fix |
| ------- | --- |
| `CURSOR_API_KEY is not set` | Add key to repo `.env` or `~/.cursor/subagents/.env`; use `--cwd` |
| `FrozenInstanceError: cannot assign to field 'local'` during recovery | Update to the version that builds immutable `cursor-sdk.AgentOptions` in the constructor |
| `RuntimeError: Daemon failed to start within timeout` after an open session exists | Run daemon from a checkout with the recovery fix; verify `CURSOR_API_KEY` is resolvable from the session cwd |
| `sqlite3.OperationalError: disk I/O error` | Check `df -h /`; free root space or move rebuildable caches such as `UV_CACHE_DIR` to `/data` |
| `nats-server not found` on Linux | Run `bash scripts/install-nats-server.sh`; the script installs to `~/.cursor/subagents/bin/nats-server` |
| `[WinError 10038]` on spawn | Update to latest package (includes Windows bridge bootstrap) |
| `watch` shows no events | Run `cursor-subagent bus start`, then restart the daemon so it binds a NATS publisher |
| `send --watch` hangs | Update to the version where the CLI connects WebSocket before starting the REST send |
| Daemon stale after code change | `cursor-subagent daemon stop && cursor-subagent daemon start` |
