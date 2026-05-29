"""Load repo-local ``.env`` files for CLI and daemon operations.

Users keep secrets such as ``CURSOR_API_KEY`` in the repository they are
automating. The daemon may run from a different working directory, so env files
are resolved from each command's ``--cwd`` (or the CLI's current directory), not
only from where the daemon process was started.
"""

from __future__ import annotations

import os
from pathlib import Path


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].strip()
    if "=" not in stripped:
        return None
    key, _, value = stripped.partition("=")
    key = key.strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    if not key:
        return None
    return key, value


def load_env_file(path: Path) -> None:
    """Merge key/value pairs from ``path`` into ``os.environ`` when unset."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(line)
        if parsed is None:
            continue
        key, value = parsed
        os.environ.setdefault(key, value)


def find_dotenv(start: Path) -> Path | None:
    """Find a ``.env`` file by walking up from ``start`` within the same repo.

    Walks from ``start`` toward filesystem root. Returns the first ``.env``
    found. Stops at the repository root (directory containing ``.git``) when no
    ``.env`` has been found yet, so we do not load env files from parent repos.
    """
    current = start.resolve()
    if not current.is_dir():
        current = current.parent

    for directory in [current, *current.parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
        if (directory / ".git").exists():
            break
    return None


def load_env_for_cwd(cwd: str | Path) -> Path | None:
    """Load ``.env`` discovered from ``cwd`` (or an ancestor within the repo)."""
    env_path = find_dotenv(Path(cwd))
    if env_path is not None:
        load_env_file(env_path)
    return env_path


def load_env_files() -> None:
    """Bootstrap env from the invoking shell cwd and the global subagents file."""
    load_env_for_cwd(Path.cwd())
    load_env_file(Path.home() / ".cursor" / "subagents" / ".env")
