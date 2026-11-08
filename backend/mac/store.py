"""Run history and event logs, in SQLite. A run can wait at a manual gate for hours, so
everything the runner needs to continue lives here, not in memory."""

import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class StepState(StrEnum):
    PENDING = "pending"
    BLOCKED = "blocked"  # waiting for an approval
    WAITING = "waiting"  # manual step, waiting for someone to press play
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"
    SKIPPED = "skipped"  # never reached because an earlier step failed


class RunStatus(StrEnum):
    RUNNING = "running"
    WAITING = "waiting"  # on an approval or a manual step
    ROLLING_BACK = "rolling_back"
    SUCCEEDED = "succeeded"  # Build passed / Rehearse passed and cleaned up / Deploy finished
    FAILED = "failed"  # a step failed and everything was undone cleanly
    ROLLBACK_FAILED = "rollback_failed"  # undo didn't finish; a person has to clean up
    UNDONE = "undone"  # someone pressed undo

    @property
    def active(self) -> bool:
        return self in (RunStatus.RUNNING, RunStatus.WAITING, RunStatus.ROLLING_BACK)


class RunRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    migration: str
    mode: str  # build | rehearse | deploy
    spec_path: str
    spec_digest: str
    spec_text: str  # the exact migration.yaml this run used; undo and resume read this, not the file
    status: RunStatus = RunStatus.RUNNING
    next_action: str | None = None  # queued work for Runner.execute: build | advance | undo
    shas: dict[str, str] = {}  # RepoRef.key -> commit this run uses
    overrides: dict[str, str] = {}  # RepoRef.key -> ref used instead of the spec's (auto-fix branches)
    steps: dict[str, StepState] = {}
    completed: list[str] = []  # step ids in the order they succeeded; rollback reverses it
    played: list[str] = []  # manual steps someone pressed play on
    failed_step: str | None = None
    reason: str | None = None
    diagnostics_mode: str = "explain"
    report: dict = {}  # Build: guardrails, approvals, plans, issues
    based_on: str | None = None  # the Build (for Rehearse) or Rehearse (for Deploy) this relies on
    created: float = Field(default_factory=time.time)
    updated: float = Field(default_factory=time.time)


class Event(BaseModel):
    run_id: str
    seq: int
    ts: float
    step: str | None
    kind: str  # log | step | run | diagnosis
    message: str


class Store:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.Lock()
        self.listeners: list[Callable[[Event], None]] = []
        with self.lock, self.db:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, migration TEXT NOT NULL, mode TEXT NOT NULL,
                    created REAL NOT NULL, data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS runs_by_migration ON runs (migration, mode, created);
                CREATE TABLE IF NOT EXISTS events (
                    run_id TEXT NOT NULL, seq INTEGER NOT NULL, ts REAL NOT NULL, step TEXT,
                    kind TEXT NOT NULL, message TEXT NOT NULL, PRIMARY KEY (run_id, seq));
                """
            )

    def save(self, run: RunRecord) -> None:
        run.updated = time.time()
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO runs (id, migration, mode, created, data) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (id) DO UPDATE SET data = excluded.data",
                (run.id, run.migration, run.mode, run.created, run.model_dump_json()),
            )

    def get(self, run_id: str) -> RunRecord:
        with self.lock:
            row = self.db.execute("SELECT data FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"no run {run_id!r}")
        return RunRecord.model_validate_json(row[0])

    def latest(self, migration: str, mode: str | None = None) -> RunRecord | None:
        query = "SELECT data FROM runs WHERE migration = ?" + (" AND mode = ?" if mode else "")
        params = (migration, mode) if mode else (migration,)
        with self.lock:
            row = self.db.execute(query + " ORDER BY created DESC, rowid DESC LIMIT 1", params).fetchone()
        return RunRecord.model_validate_json(row[0]) if row else None

    def runs(self, migration: str | None = None, limit: int = 50) -> list[RunRecord]:
        query = "SELECT data FROM runs" + (" WHERE migration = ?" if migration else "")
        params = (migration,) if migration else ()
        with self.lock:
            rows = self.db.execute(query + " ORDER BY created DESC, rowid DESC LIMIT ?", (*params, limit)).fetchall()
        return [RunRecord.model_validate_json(r[0]) for r in rows]

    def add_event(self, run_id: str, kind: str, message: str, step: str | None = None) -> Event:
        with self.lock, self.db:
            seq = self.db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE run_id = ?",
                                  (run_id,)).fetchone()[0]
            event = Event(run_id=run_id, seq=seq, ts=time.time(), step=step, kind=kind, message=message)
            self.db.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)",
                            (run_id, seq, event.ts, step, kind, message))
        for listener in self.listeners:
            listener(event)
        return event

    def events(self, run_id: str, after: int = 0, step: str | None = None) -> list[Event]:
        query = "SELECT run_id, seq, ts, step, kind, message FROM events WHERE run_id = ? AND seq > ?"
        params: tuple = (run_id, after)
        if step is not None:
            query += " AND step = ?"
            params += (step,)
        with self.lock:
            rows = self.db.execute(query + " ORDER BY seq", params).fetchall()
        return [Event(run_id=r[0], seq=r[1], ts=r[2], step=r[3], kind=r[4], message=r[5]) for r in rows]
