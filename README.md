# Cursor Sub-Agent v0.2

Stateful Cursor sub-agent orchestration with a **NATS event bus** and **Rust WebSocket gateway**.

## Architecture

| Component | Role |
| --------- | ---- |
| `cursor-subagentd` | Python REST daemon, session manager, cursor-sdk providers, SQLite |
| `nats-server` | Pub/sub event bus for session and wave streams |
| `subagent-gateway` | Rust WebSocket bridge (nats.rs + axum) |
| `cursor-subagent` | CLI client for REST + gateway watch |

## Install

```bash
cd d:\code\automations
pip install -e ".[dev]"

# NATS broker
powershell -ExecutionPolicy Bypass -File scripts/install-nats-server.ps1

# Rust gateway
cargo build --release -p subagent-gateway
```

Set `CURSOR_API_KEY` for live Cursor sessions.

## Start stack

```bash
cursor-subagent bus start      # nats-server + subagent-gateway
cursor-subagent daemon start   # Python REST daemon (auto-starts on first command)
```

## Usage

```bash
# Spawn stateful session
cursor-subagent spawn --task "Create hello.txt" --cwd . --json

# Follow-up (same session, full context)
cursor-subagent send <sessionId> "Add a timestamp" --json

# Live stream via Rust gateway
cursor-subagent watch <sessionId>

# Resume from known Cursor agent ID
cursor-subagent resume --agent-id agent-xyz --cwd . --task "Continue work" --json

# Replay persisted automation template
cursor-subagent spawn --from-template <oldSessionId> --task "Run again" --json

# Wave orchestration
cursor-subagent wave create --wave-id wave-1 --goal "..." --tasks tasks.json
cursor-subagent wave spawn wave-1 --json
cursor-subagent wave close wave-1 --json
```

## Environment

| Variable | Default |
| -------- | ------- |
| `CURSOR_API_KEY` | required for live Cursor |
| `SUBAGENT_NATS_URL` | `nats://127.0.0.1:4222` |
| `SUBAGENT_GATEWAY_URL` | `ws://127.0.0.1:17341` |
| `SUBAGENT_DAEMON_URL` | `http://127.0.0.1:17340` |
| `SUBAGENT_GATEWAY_BIN` | `bus/target/release/subagent-gateway(.exe)` |
| `SUBAGENT_NATS_SERVER_BIN` | `~/.cursor/subagents/bin/nats-server(.exe)` |

## Tests

```bash
python -m pytest -q                 # unit tests (mocked provider)
python -m pytest -q -m integration  # requires bus start
```

## Skill

Agent workflow: [`.cursor/skills/cursor-subagent/SKILL.md`](.cursor/skills/cursor-subagent/SKILL.md)
