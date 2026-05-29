from __future__ import annotations

from cursor_subagent.env import load_env_files
from cursor_subagent.daemon.app import run_server

load_env_files()


def main() -> None:
    run_server()


if __name__ == "__main__":
    main()
