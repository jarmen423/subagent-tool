# Cursor Sub-Agent

Stateful Cursor sub-agent daemon and CLI for multi-agent orchestration. v1 runs **Composer 2.5** via `cursor-sdk`; the provider layer is designed for future backends (Claude Code, KimiCode, GrokBuild, etc.).

## Install

```bash
cd d:\code\automations
pip install -e ".[dev]"
```

Set your API key:

```bash
export CURSOR_API_KEY="cursor_..."
```

## Quick start

```bash
# Start daemon (or auto-starts on first command)
cursor-subagent daemon start

# Spawn a stateful session
cursor-subagent spawn --task "Create hello.txt with a greeting" --cwd . --json

# Send follow-ups (same session, full conversation context)
cursor-subagent send ses_abc123 "Make the greeting more formal" --json

# Monitor live
cursor-subagent watch ses_abc123

# Close when done
cursor-subagent close ses_abc123 --json
```

## Wave orchestration

```bash
cursor-subagent wave create \
  --wave-id wave-auth \
  --goal "Refactor auth module" \
  --tasks tasks.json

cursor-subagent wave spawn wave-auth --cwd . --json
cursor-subagent wave status wave-auth --json
cursor-subagent wave close wave-auth --json
```

Example `tasks.json`:

```json
{
  "tasks": [
    {
      "taskId": "T1",
      "goal": "Refactor auth middleware",
      "ownedPaths": ["src/auth/"],
      "handoffPath": ".planning/execution/handoffs/wave-auth/T1.md"
    }
  ]
}
```

## Architecture

- **`cursor-subagentd`** — long-running daemon holding in-memory SDK agent handles
- **SQLite** — session metadata, runs, events, waves at `~/.cursor/subagents/subagents.db`
- **CLI** — thin HTTP/WebSocket client (`127.0.0.1:17340` by default)

Environment variables:

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `CURSOR_API_KEY` | — | Required for Cursor provider |
| `SUBAGENT_DAEMON_URL` | `http://127.0.0.1:17340` | Daemon base URL |
| `SUBAGENT_DAEMON_PORT` | `17340` | Daemon port |
| `SUBAGENT_DB_PATH` | `~/.cursor/subagents` | SQLite directory |

## Skill

Agent workflow docs live at [`.cursor/skills/cursor-subagent/SKILL.md`](.cursor/skills/cursor-subagent/SKILL.md). Copy to `~/.cursor/skills/cursor-subagent/` for global use.

## Tests

```bash
pytest
```

Integration tests against live Cursor require `CURSOR_API_KEY`:

```bash
cursor-subagent spawn --task "Reply with the word ok" --cwd . --json
```
