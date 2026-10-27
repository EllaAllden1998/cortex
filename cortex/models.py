"""Data shapes shared by the store, the compiler, the runtime and the API."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Note(BaseModel):
    id: str
    area: str
    type: str
    description: str
    body: str
    links: list[str] = []
    modified: date


class Event(BaseModel):
    """One line of the brain's activity log: an agent read (collect) or wrote (push) a note."""
    ts: datetime
    session: str
    op: Literal["push", "collect"]
    note: str


class Evidence(BaseModel):
    note_id: str
    area: str
    quote: str
    score: float
    modified: date
    age_days: int


class TraceEvent(BaseModel):
    step: str
    kind: str
    status: Literal["ok", "pass", "fail", "skipped"]
    ms: float
    cost_usd: float = 0.0
    detail: dict[str, Any] = {}


Outcome = Literal["answered", "refused"]


class RunResult(BaseModel):
    run_id: str
    graph_id: str
    graph_version: int
    plan_hash: str
    question: str
    outcome: Outcome
    answer: str | None
    confidence: float
    route: list[str]
    evidence: list[Evidence]
    trace: list[TraceEvent]
    cost_usd: float
    started_at: datetime


class RunRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
