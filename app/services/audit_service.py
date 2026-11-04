"""Audit trail + application log helpers."""
from __future__ import annotations

import logging
from collections import deque
from pathlib import Path

from flask import has_request_context, request
from flask_login import current_user

from app.extensions import db
from app.models import AuditEvent

log = logging.getLogger("sdp.audit")


def audit(action: str, detail: str = "", user_id: int | None = None, commit: bool = True) -> None:
    if user_id is None and has_request_context() and current_user.is_authenticated:
        user_id = current_user.id
    ip = request.remote_addr if has_request_context() else None
    db.session.add(AuditEvent(user_id=user_id, action=action, detail=detail[:2000], ip=ip))
    if commit:
        db.session.commit()
    log.info("audit action=%s user=%s detail=%s", action, user_id, detail[:200])


def tail_log(path: Path, lines: int = 200) -> list[str]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", errors="replace") as fh:
        return [ln.rstrip("\n") for ln in deque(fh, maxlen=lines)]
