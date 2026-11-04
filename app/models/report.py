"""Submission (what was uploaded) and Report (the analysis result for it)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.user import User, utcnow


class Submission(db.Model):
    """Persistent record of a CodeRepository ingestion (file / zip / git)."""
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(10), nullable=False)  # file | zip | git
    source_name: Mapped[str] = mapped_column(String(500), nullable=False)
    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    user: Mapped[User] = relationship()

    @property
    def meta(self) -> dict:
        return json.loads(self.meta_json or "{}")


class ReportStatus:
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Report(db.Model):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default=ReportStatus.RUNNING)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Denormalised summary for fast listing / sorting.
    n_files: Mapped[int] = mapped_column(Integer, default=0)
    n_high: Mapped[int] = mapped_column(Integer, default=0)
    n_medium: Mapped[int] = mapped_column(Integer, default=0)
    n_low: Mapped[int] = mapped_column(Integer, default=0)
    max_probability: Mapped[float] = mapped_column(Float, default=0.0)
    model_versions: Mapped[str | None] = mapped_column(String(200))

    payload_json: Mapped[str | None] = mapped_column(Text)

    submission: Mapped[Submission] = relationship()
    user: Mapped[User] = relationship()

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json) if self.payload_json else {}

    def set_payload(self, payload: dict[str, Any]) -> None:
        self.payload_json = json.dumps(payload)
        s = payload["summary"]
        rc = s["risk_counts"]
        self.n_files = s["files"]
        self.n_high, self.n_medium, self.n_low = rc["High"], rc["Medium"], rc["Low"]
        self.max_probability = s["max_probability"]
        models = payload.get("models", {})
        self.model_versions = ", ".join(
            f"{lvl}:v{m['version']}" for lvl, m in models.items() if m)

    @property
    def is_done(self) -> bool:
        return self.status == ReportStatus.DONE

    def visible_to(self, user: User) -> bool:
        return user.can_view_all_reports or user.id == self.user_id
