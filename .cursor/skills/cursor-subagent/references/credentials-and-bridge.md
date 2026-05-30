# Credentials and SDK Bridge

## CURSOR_API_KEY resolution

Loaded automatically when CLI or daemon handles spawn/resume. **First unset slot wins** (`setdefault` — existing env vars are never overwritten).

| Priority | Source | Typical use |
| -------- | ------ | ----------- |
| 1 | `CURSOR_API_KEY` in process environment | CI, exported shell, secret manager |
| 2 | `<repo>/.env` | Per-project automation (preferred for agents) |
| 3 | `~/.cursor/subagents/.env` | One key for all repos on this machine |

### Repo `.env` discovery

Starting from resolved `--cwd`, walk up directories until:

- A `.env` file is found → load it, or
- A `.git` directory is found → stop (do not load parent repos)

Example: `--cwd /projects/myapp/packages/api` loads `/projects/myapp/.env` if present.

### Example `.env` (gitignored)

```bash
CURSOR_API_KEY=cursor_...
```

Mint keys: https://cursor.com/dashboard/cloud-agents

### Agent checklist

- [ ] Target repo has `.env` **or** global `~/.cursor/subagents/.env` exists
- [ ] `--cwd` is absolute path to that repo
- [ ] Never cat/log/commit `.env`
- [ ] On auth error, verify key prefix starts with `cursor_` (do not print full key)

---

## What is the cursor-sdk bridge?

The **cursor-sdk bridge** (`cursor-sdk-bridge`) is a sidecar binary bundled with the Python `cursor-sdk` package. The SDK does not run local agents purely in-process:

```
cursor-subagent daemon
  → cursor-sdk (Python client)
    → cursor-sdk-bridge (subprocess, local HTTP/Connect server)
      → Cursor local agent runtime (edits files in --cwd)
```

On startup the bridge prints a discovery line to stderr:

```
cursor-sdk-bridge ready {"url":"http://...","authToken":"..."}
```

The SDK connects using that URL and token for all local agent RPCs (create, send, stream, wait).

### Is the bridge Windows-only?

**No.** The bridge is required for **local runtime via the Python SDK on all platforms.**

| Platform | Bridge required? | Who starts it? |
| -------- | ---------------- | -------------- |
| macOS / Linux | Yes | `cursor-sdk` auto-launches via `Bridge.launch()` |
| Windows | Yes | **cursor-subagent** pre-launches (`bridge_bootstrap.py`) because SDK auto-launch fails with `WinError 10038` (`select()` on pipe handles) |

Agents on Windows do not need manual bridge setup — the provider calls `ensure_sdk_bridge(cwd)` before `Agent.create()`.

### Manual bridge attach (advanced)

If you already run a bridge, set before spawning:

```bash
export CURSOR_SDK_BRIDGE_URL=http://127.0.0.1:PORT
export CURSOR_SDK_BRIDGE_TOKEN=...
```

The SDK skips auto-launch when both are set.

---

## Local vs cloud runtime

| | `--runtime local` (default) | `--runtime cloud --repo URL` |
| --- | --- | --- |
| Where agent runs | Your machine | Cursor cloud VM |
| Files | Live `--cwd` checkout | Cloned repo |
| Bridge | Required (Python SDK) | SDK still uses default client/bridge pattern |
| Use when | Dev automation, uncommitted work | Long jobs, PR-based workflows |

v1 default and best-tested path: **local** with `--cwd`.
