Try the full stack:
```shell
pip install -e ".[dev]"
powershell -file scripts/install-nats-server.ps1
cargo build --release -p subagent-gateway
cursor-subagent bus start
cursor-subagent spawn --task "reply ok" --cwd . --json
```

After first use:
```shell
cursor-subagent daemon start
cursor-subagent spawn --task "Reply ok" --cwd . --json
cursor-subagent watch <sessionId>
```
