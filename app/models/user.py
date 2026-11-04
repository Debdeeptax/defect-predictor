"""User — account with a single role (Developer, QA Engineer, Admin)."""
from __future__ import annotations

from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Role:
    DEVELOPER = "developer"
    QA = "qa"
    ADMIN = "admin"
    ALL = (DEVELOPER, QA, ADMIN)
    LABELS = {DEVELOPER: "Developer", QA: "QA Engineer", ADMIN: "Admin"}


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=Role.DEVELOPER)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self) -> bool:  # Flask-Login: inactive users cannot log in
        return self.active

    @property
    def role_label(self) -> str:
        return Role.LABELS.get(self.role, self.role)

    def has_role(self, *roles: str) -> bool:
        return self.role in roles

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def can_submit(self) -> bool:
        return self.role in (Role.DEVELOPER, Role.ADMIN)

    @property
    def can_view_all_reports(self) -> bool:
        return self.role in (Role.QA, Role.ADMIN)

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role})>"
