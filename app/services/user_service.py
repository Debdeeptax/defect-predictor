"""Account management: registration, authentication, role / status changes."""
from __future__ import annotations

import re

from app.exceptions import SDPError
from app.extensions import db
from app.models import Role, User
from app.models.user import utcnow

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserError(SDPError):
    user_message = "Invalid user operation."


def validate_password(password: str) -> None:
    if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise UserError("Password must be at least 8 characters and contain letters and digits.")


def register(email: str, name: str, password: str, role: str = Role.DEVELOPER) -> User:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise UserError("Please enter a valid email address.")
    if not (name or "").strip():
        raise UserError("Please enter your name.")
    validate_password(password)
    if role not in Role.ALL:
        raise UserError("Unknown role.")
    if db.session.scalar(db.select(User).filter_by(email=email)):
        raise UserError("An account with this email already exists.")
    user = User(email=email, name=name.strip(), role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def authenticate(email: str, password: str) -> User | None:
    user = db.session.scalar(db.select(User).filter_by(email=(email or "").strip().lower()))
    if user is None or not user.check_password(password or ""):
        return None
    return user


def mark_login(user: User) -> None:
    user.last_login_at = utcnow()
    db.session.commit()


def set_role(actor: User, user: User, role: str) -> None:
    if role not in Role.ALL:
        raise UserError("Unknown role.")
    if user.id == actor.id and role != Role.ADMIN:
        raise UserError("You cannot remove your own admin role.")
    user.role = role
    db.session.commit()


def set_active(actor: User, user: User, active: bool) -> None:
    if user.id == actor.id and not active:
        raise UserError("You cannot deactivate your own account.")
    user.active = active
    db.session.commit()
