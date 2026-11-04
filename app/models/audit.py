"""AuditEvent (who did what) and TrainingJob (background retrain runs)."""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.user import User, utcnow


class AuditEvent(db.Model):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True, nullable=False)

    user: Mapped[User | None] = relationship()


class JobStatus:
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    ACTIVE = (QUEUED, RUNNING)


class TrainingJob(db.Model):
    __tablename__ = "training_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    source: Mapped[str] = mapped_column(String(300), nullable=False)  # "builtin" or csv filename
    folds: Mapped[int] = mapped_column(Integer, nullable=False)
    repeats: Mapped[int] = mapped_column(Integer, nullable=False)
    activate: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(10), default=JobStatus.QUEUED, nullable=False)
    started_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    log: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text)
    result_json: Mapped[str | None] = mapped_column(Text)

    started_by: Mapped[User] = relationship()

    @property
    def result(self) -> dict:
        return json.loads(self.result_json) if self.result_json else {}

    @property
    def is_finished(self) -> bool:
        return self.status in (JobStatus.DONE, JobStatus.FAILED)
