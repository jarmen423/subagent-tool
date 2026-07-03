from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL DEFAULT 'cursor-composer',
  agent_id TEXT,
  cwd TEXT NOT NULL,
  model TEXT NOT NULL,
  runtime TEXT NOT NULL,
  status TEXT NOT NULL,
  wave_id TEXT,
  task_id TEXT,
  task_summary TEXT,
  persist INTEGER DEFAULT 0,
  repo_url TEXT,
  created_at TEXT,
  updated_at TEXT,
  closed_at TEXT
);

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  session_id TEXT REFERENCES sessions(id),
  status TEXT,
  result TEXT,
  started_at TEXT,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT,
  run_id TEXT,
  type TEXT,
  payload_json TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS waves (
  id TEXT PRIMARY KEY,
  goal TEXT,
  tasks_json TEXT,
  status TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS automations (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  task TEXT NOT NULL,
  cwd TEXT NOT NULL,
  provider TEXT NOT NULL DEFAULT 'cursor-composer',
  model TEXT NOT NULL,
  runtime TEXT NOT NULL,
  repo_url TEXT,
  cron_expression TEXT,
  webhook_enabled INTEGER DEFAULT 0,
  webhook_secret_hash TEXT,
  status TEXT NOT NULL,
  memory_summary TEXT,
  recent_run_count INTEGER DEFAULT 5,
  next_run_at TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS automation_runs (
  id TEXT PRIMARY KEY,
  automation_id TEXT REFERENCES automations(id),
  trigger_type TEXT NOT NULL,
  trigger_payload_json TEXT,
  rendered_prompt TEXT NOT NULL,
  session_id TEXT,
  status TEXT NOT NULL,
  result TEXT,
  error TEXT,
  memory_update TEXT,
  started_at TEXT,
  finished_at TEXT
);
"""


def default_db_path() -> Path:
    base = Path(os.environ.get("SUBAGENT_DB_PATH", Path.home() / ".cursor" / "subagents"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "subagents.db"


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or default_db_path()
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
