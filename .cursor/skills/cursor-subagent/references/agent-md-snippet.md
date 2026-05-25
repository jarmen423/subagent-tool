## Sub-agents (Cursor / Composer 2.5)

For implementation work, delegate to stateful Cursor sub-agents via the daemon:

1. Ensure daemon is running: `cursor-subagent daemon start`
2. For parallel waves, use the **wave-execution** skill + `cursor-subagent wave create/spawn`
3. For single tasks: `cursor-subagent spawn --task "<precise task with owned paths>" --cwd . --json`
4. Iterate on the **same session**: `cursor-subagent send <sessionId> "<feedback>" --json`
5. Monitor: `cursor-subagent watch <sessionId>` or `cursor-subagent wave status <waveId>`
6. Always close: `cursor-subagent close <sessionId>` or `cursor-subagent wave close <waveId>`

Requires `CURSOR_API_KEY`. Read the `cursor-subagent` skill for full workflow.
