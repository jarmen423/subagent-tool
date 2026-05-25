# Daemon and CLI Reference

Default daemon URL: `http://127.0.0.1:17340`

## Daemon management

| Command | Description |
| ------- | ----------- |
| `cursor-subagent daemon start` | Start background daemon |
| `cursor-subagent daemon stop` | Stop daemon |
| `cursor-subagent daemon status [--json]` | Health check |

## Session commands

| Command | Description |
| ------- | ----------- |
| `spawn --task TEXT [--cwd .] [--provider cursor-composer] [--model composer-2.5] [--runtime local] [--repo URL] [--persist] [--json]` | Create session + run first task |
| `send <sessionId> "message" [--json] [--watch]` | Follow-up message (stateful) |
| `watch <sessionId> [--json]` | WebSocket event stream |
| `status <sessionId> [--json]` | Session + latest run metadata |
| `events <sessionId> [--since RUN] [--json]` | Replay stored events |
| `cancel <sessionId> [--json]` | Cancel active run |
| `close <sessionId> [--json]` | Dispose handle; purge unless `--persist` or wave-linked |
| `list [--cwd .] [--wave ID] [--status STATUS] [--json]` | List sessions |

## Wave commands

| Command | Description |
| ------- | ----------- |
| `wave create --wave-id ID --goal TEXT --tasks FILE [--json]` | Register wave |
| `wave spawn <waveId> [--task-ids T1,T2] [--cwd .] [--json]` | Spawn one session per task |
| `wave status <waveId> [--json]` | Wave + linked sessions |
| `wave close <waveId> [--json]` | Close all wave sessions |

## HTTP API

| Method | Path |
| ------ | ---- |
| GET | `/health` |
| POST | `/sessions` |
| GET | `/sessions` |
| GET | `/sessions/{id}` |
| POST | `/sessions/{id}/messages` |
| WS | `/sessions/{id}/stream` |
| GET | `/sessions/{id}/events` |
| POST | `/sessions/{id}/cancel` |
| DELETE | `/sessions/{id}` |
| POST | `/waves` |
| GET | `/waves/{id}` |
| POST | `/waves/{id}/spawn` |
| POST | `/waves/{id}/close` |

## Exit codes

- `0` — success
- `1` — startup / HTTP error
- `2` — run failed after starting

## JSON response shape

```json
{
  "session_id": "ses_abc123",
  "agent_id": "agent-xyz",
  "run_id": "run-def",
  "status": "idle",
  "result": "final assistant text",
  "cwd": "d:\\code\\myproject",
  "model": "composer-2.5",
  "provider": "cursor-composer",
  "stream_url": "/sessions/ses_abc123/stream"
}
```
