from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, ConfigDict


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStatus(str, Enum):
    OPEN = "open"
    RUNNING = "running"
    IDLE = "idle"
    CLOSED = "closed"


class RunStatus(str, Enum):
    RUNNING = "running"
    FINISHED = "finished"
    ERROR = "error"
    CANCELLED = "cancelled"


class WaveStatus(str, Enum):
    OPEN = "open"
    RUNNING = "running"
    CLOSED = "closed"


class WaveTask(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    task_id: str = Field(alias="taskId")
    goal: str
    owned_paths: list[str] = Field(default_factory=list, alias="ownedPaths")
    handoff_path: str | None = Field(default=None, alias="handoffPath")
    provider: str = "cursor-composer"
    cwd: str | None = None
    model: str = "composer-2.5"


class WaveDefinition(BaseModel):
    wave_id: str
    goal: str
    tasks: list[WaveTask] = Field(default_factory=list)


class SessionRecord(BaseModel):
    id: str
    provider: str = "cursor-composer"
    agent_id: str | None = None
    cwd: str
    model: str = "composer-2.5"
    runtime: str = "local"
    status: SessionStatus = SessionStatus.OPEN
    wave_id: str | None = None
    task_id: str | None = None
    task_summary: str | None = None
    persist: bool = False
    repo_url: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    closed_at: str | None = None


class RunRecord(BaseModel):
    id: str
    session_id: str
    status: RunStatus = RunStatus.RUNNING
    result: str | None = None
    started_at: str = Field(default_factory=utc_now_iso)
    finished_at: str | None = None


class EventRecord(BaseModel):
    id: int | None = None
    session_id: str
    run_id: str
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)


class WaveRecord(BaseModel):
    id: str
    goal: str
    tasks: list[WaveTask] = Field(default_factory=list)
    status: WaveStatus = WaveStatus.OPEN
    created_at: str = Field(default_factory=utc_now_iso)


class SpawnSessionRequest(BaseModel):
    task: str
    cwd: str = "."
    provider: str = "cursor-composer"
    model: str = "composer-2.5"
    runtime: str = "local"
    repo_url: str | None = None
    persist: bool = False
    wave_id: str | None = None
    task_id: str | None = None


class SendMessageRequest(BaseModel):
    message: str


class CreateWaveRequest(BaseModel):
    wave_id: str
    goal: str
    tasks: list[WaveTask]


class WaveSpawnRequest(BaseModel):
    task_ids: list[str] | None = None
    cwd: str = "."


class SessionResponse(BaseModel):
    session_id: str
    agent_id: str | None = None
    run_id: str | None = None
    status: str
    result: str | None = None
    cwd: str
    model: str
    provider: str
    wave_id: str | None = None
    task_id: str | None = None
    stream_url: str | None = None


class WaveStatusResponse(BaseModel):
    wave_id: str
    goal: str
    status: str
    sessions: list[SessionResponse] = Field(default_factory=list)
