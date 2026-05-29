# Cursor Sub-Agent Runbook

## First-time setup

```shell
pip install -e ".[dev]"
powershell -File scripts/install-nats-server.ps1
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

## Smoke test (live Cursor)

```shell
cursor-subagent spawn \
  --task "Create scripts/hello_subagent.py: def main() prints 'Hello from subagent'" \
  --cwd . --json

python scripts/hello_subagent.py
cursor-subagent close <sessionId> --json
```

Expected script output: `Hello from subagent`

## Agent delegation pattern

Main agents should:

1. `cursor-subagent bus start` (once per machine/session if not running)
2. `cursor-subagent spawn --task "..." --cwd /absolute/path/to/target/repo --json`
3. Parse JSON for `session_id`, `result`, `stream_url`
4. Optional: `cursor-subagent watch <sessionId>` for live events
5. Follow-ups: `cursor-subagent send <sessionId> "..." --json`
6. Always: `cursor-subagent close <sessionId> --json`

## Troubleshooting

| Symptom | Fix |
| ------- | --- |
| `CURSOR_API_KEY is not set` | Add key to repo `.env` or `~/.cursor/subagents/.env`; use `--cwd` |
| `[WinError 10038]` on spawn | Update to latest package (includes Windows bridge bootstrap) |
| `watch` shows no events | Run `cursor-subagent bus start` first |
| Daemon stale after code change | `cursor-subagent daemon stop && cursor-subagent daemon start` |
