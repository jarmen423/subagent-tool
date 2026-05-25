---
name: cursor-subagent
description: >-
  Delegate work to stateful Cursor sub-agents (Composer 2.5) via the cursor-subagent
  daemon and CLI. Use when spawning sub-agents from Codex, Claude Code, or other
  main agents; orchestrating parallel waves with wave-execution; running
  cursor-subagent spawn/send/watch/close; or when CURSOR_API_KEY and multi-turn
  sub-agent sessions are needed.
disable-model-invocation: true
---

# Cursor Sub-Agent

## Overview

Use the **cursor-subagent daemon** to run stateful Composer 2.5 sessions. Spawn once, send many follow-ups, monitor over WebSocket, close when done. For parallel work, combine with the **wave-execution** skill.

Load [`references/daemon-and-cli-reference.md`](references/daemon-and-cli-reference.md) for full command details.

## Prerequisites

1. Install: `pip install -e .` from the automations repo (or `pip install cursor-subagent` when published)
2. Export `CURSOR_API_KEY`
3. Start daemon: `cursor-subagent daemon start` (auto-starts on first command if omitted)

## When to delegate

- Disjoint implementation tasks with clear write scopes
- Parallel wave tracks (use `wave create` / `wave spawn`)
- Repo-local coding the main agent should not do inline
- Multi-turn iteration where the sub-agent must retain context

Do **not** spawn a new session per message — use `send` on the same `sessionId`.

## Core workflow (single task)

```bash
cursor-subagent spawn --task "<precise task with owned paths>" --cwd . --json
cursor-subagent send <sessionId> "<feedback or follow-up>" --json
cursor-subagent watch <sessionId>          # optional live stream
cursor-subagent status <sessionId> --json
cursor-subagent close <sessionId> --json     # always close when done
```

## Wave orchestration

Cross-ref **wave-execution** skill. Before spawning:

1. Lock task ids, write scopes, and handoff paths
2. Register the wave:

```bash
cursor-subagent wave create --wave-id wave-1 --goal "..." --tasks tasks.json --json
cursor-subagent wave spawn wave-1 --cwd . --json
cursor-subagent wave status wave-1 --json
```

3. Monitor sessions; send corrective `send` messages if needed
4. Close when gate passes: `cursor-subagent wave close wave-1 --json`

## Rules for main agents

- One session per delegated task; reuse via `send`
- Always `close` sessions (or `wave close`) when finished
- Never log or paste `CURSOR_API_KEY`
- Parse `--json` stdout for automation
- Parallel sessions require **disjoint write scopes** (wave-execution ownership rules)
- v1 provider: `cursor-composer` only; `--provider` reserved for future backends

## AGENTS.md snippet

See [`references/agent-md-snippet.md`](references/agent-md-snippet.md) for copy-paste instructions.
