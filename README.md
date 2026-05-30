# Cursor Sub-Agent v0.2

Stateful Cursor sub-agent orchestration with a **NATS event bus** and **Rust WebSocket gateway**.

## Architecture

| Component | Role |
| -------- | ---- |
| `cursor-subagentd` | Python REST daemon, session manager, cursor-sdk providers, SQLite |
| `nats-server` | Pub/sub event bus for session and wave streams |
| `subagent-gateway` | Rust WebSocket bridge (nats.rs + axum) |
| `cursor-subagent` | CLI client for REST + gateway watch |

## Install

```bash
cd /data/code/subagent-tool
pip install -e ".[dev]"
```

Linux/macOS:

```bash
bash scripts/install-nats-server.sh
cargo build --release -p subagent-gateway --manifest-path bus/Cargo.toml
```

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install-nats-server.ps1
cargo build --release -p subagent-gateway
```

## Credentials (`CURSOR_API_KEY`)

Mint a key at [cursor.com/dashboard/cloud-agents](https://cursor.com/dashboard/cloud-agents).

The tool resolves credentials at **spawn time** from the repo you pass via `--cwd`:

| Priority | Source | Use case |
| -------- | ------ | -------- |
| 1 | `CURSOR_API_KEY` already in the environment | CI, shell profile |
| 2 | Repo `.env` (walks up from `--cwd` to `.git` root) | Per-project automation |
| 3 | `~/.cursor/subagents/.env` | Machine-wide default |

Example repo `.env` (gitignored):

```bash
CURSOR_API_KEY=cursor_...
```

**Agents:** always pass `--cwd` to the target repository. Never log or commit `.env`.

## Start stack

```bash
cursor-subagent bus start      # nats-server + subagent-gateway
cursor-subagent daemon start   # Python REST daemon (auto-starts on first command)
cursor-subagent bus status --json
cursor-subagent daemon status --json
```

On Linux, `bus start` and `daemon start` detach their child processes so they
remain available after the short-lived CLI command exits. Restart the daemon
after changing Python code so it picks up local source edits:

```bash
cursor-subagent daemon stop && cursor-subagent daemon start
```

## Usage

```bash
# Spawn stateful session (loads .env from --cwd)
cursor-subagent spawn --task "Create hello.txt" --cwd . --json

# Follow-up (same session, full context)
cursor-subagent send <sessionId> "Add a timestamp" --json

# Follow-up and stream the same run via the Rust gateway
cursor-subagent send <sessionId> "Add another timestamp" --watch --json

# Watch events from another shell
cursor-subagent watch <sessionId>

# Replay stored events from SQLite
cursor-subagent events <sessionId> --json

# Resume from known Cursor agent ID
cursor-subagent resume --agent-id agent-xyz --cwd . --task "Continue work" --json

# Replay persisted automation template
cursor-subagent spawn --from-template <oldSessionId> --task "Run again" --json

# Wave orchestration
cursor-subagent wave create --wave-id wave-1 --goal "..." --tasks tasks.json
cursor-subagent wave spawn wave-1 --cwd . --json
cursor-subagent wave close wave-1 --json
```

## Smoke test

With `CURSOR_API_KEY` configured and the stack running:

```bash
cursor-subagent spawn \
  --task "Create scripts/hello_subagent.py with a main() that prints Hello from subagent" \
  --cwd . --json
python scripts/hello_subagent.py
cursor-subagent close <sessionId> --json
```

## Windows note

Local runtime uses the `cursor-sdk` bridge. On Windows, the daemon pre-launches the bridge (workaround for `WinError 10038` when the SDK uses `select()` on pipe handles). No manual setup required.

Optional: if you already run a bridge, set `CURSOR_SDK_BRIDGE_URL` and `CURSOR_SDK_BRIDGE_TOKEN` before spawning.

## Linux notes

- The Unix NATS installer places `nats-server` at
  `~/.cursor/subagents/bin/nats-server`.
- The Rust gateway binary is discovered at `bus/target/release/subagent-gateway`
  unless `SUBAGENT_GATEWAY_BIN` is set.
- Repo-local `.env` files are loaded from each command's `--cwd`. This also
  matters during daemon recovery: always pass an absolute `--cwd` on spawn,
  resume, and wave commands so recovered sessions can find `CURSOR_API_KEY`.
- The daemon must start while the bus is running if `watch` should receive live
  events. If it started while NATS was down, run
  `cursor-subagent daemon stop && cursor-subagent daemon start`.
- SQLite state lives in `~/.cursor/subagents/subagents.db`. Non-persisted
  sessions are purged on close; use `--persist` when you need templates or
  durable event replay.
- Keep some free space on the root filesystem. SQLite WAL mode and local Python
  environments fail when `/` is full. If root is tight, set `UV_CACHE_DIR` to a
  path on `/data` before running `uv run`.

## Environment

| Variable | Default |
| -------- | ------- |
| `CURSOR_API_KEY` | required for live Cursor (see credentials above) |
| `SUBAGENT_NATS_URL` | `nats://127.0.0.1:4222` |
| `SUBAGENT_GATEWAY_URL` | `ws://127.0.0.1:17341` |
| `SUBAGENT_DAEMON_URL` | `http://127.0.0.1:17340` |
| `SUBAGENT_GATEWAY_BIN` | `bus/target/release/subagent-gateway(.exe)` |
| `SUBAGENT_NATS_SERVER_BIN` | `~/.cursor/subagents/bin/nats-server(.exe)` |
| `CURSOR_SDK_BRIDGE_URL` | auto on Windows; optional manual bridge |
| `CURSOR_SDK_BRIDGE_TOKEN` | paired with bridge URL |

## Tests

```bash
python -m pytest -q                         # installed dev environment
UV_CACHE_DIR=.uv-cache uv run --extra dev pytest -q
python -m pytest -q -m integration          # requires bus start
```

## Skill

Agent workflow: [`.cursor/skills/cursor-subagent/SKILL.md`](.cursor/skills/cursor-subagent/SKILL.md)
