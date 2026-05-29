from __future__ import annotations

import os
from pathlib import Path

from cursor_subagent.env import find_dotenv, load_env_for_cwd


def test_find_dotenv_walks_up_to_repo_root(tmp_path: Path) -> None:
    repo = tmp_path / "project"
    nested = repo / "packages" / "app"
    nested.mkdir(parents=True)
    (repo / ".git").mkdir()
    env_file = repo / ".env"
    env_file.write_text("CURSOR_API_KEY=cursor_test_key\n", encoding="utf-8")

    assert find_dotenv(nested) == env_file.resolve()


def test_find_dotenv_stops_at_repo_boundary(tmp_path: Path) -> None:
    outer = tmp_path / "outer"
    inner = outer / "repo" / "src"
    inner.mkdir(parents=True)
    (outer / "repo" / ".git").mkdir()
    (outer / ".env").write_text("CURSOR_API_KEY=outer\n", encoding="utf-8")

    assert find_dotenv(inner) is None


def test_load_env_for_cwd_sets_unset_variables(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text('CURSOR_API_KEY="cursor_from_repo"\n', encoding="utf-8")

    load_env_for_cwd(repo)

    assert os.environ["CURSOR_API_KEY"] == "cursor_from_repo"
