"""Deterministic seed data for demos and repeatable (Selenium) tests."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from app.extensions import db
from app.models import Report, Role, User

SEED_PASSWORD = "Test@1234"
SEED_USERS = [
    ("dev@test.com", "Dev User", Role.DEVELOPER),
    ("qa@test.com", "QA User", Role.QA),
    ("admin@test.com", "Admin User", Role.ADMIN),
]
SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "samples" / "sample_project"
SAMPLE_REPORT_TITLE = "Sample project (seed)"


def sample_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(SAMPLE_DIR.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(SAMPLE_DIR).as_posix())
    return buf.getvalue()


def seed_all(with_report: bool = True) -> list[str]:
    out = []
    users = {}
    for email, name, role in SEED_USERS:
        user = db.session.scalar(db.select(User).filter_by(email=email))
        if user is None:
            user = User(email=email, name=name, role=role)
            user.set_password(SEED_PASSWORD)
            db.session.add(user)
            out.append(f"created {role:<9} {email} / {SEED_PASSWORD}")
        else:
            out.append(f"exists  {role:<9} {email}")
        users[role] = user
    db.session.commit()

    if with_report and not db.session.scalar(db.select(Report).filter_by(title=SAMPLE_REPORT_TITLE)):
        from app.services.analysis_service import analyse_upload
        report = analyse_upload(users[Role.DEVELOPER], "sample_project.zip",
                                io.BytesIO(sample_zip_bytes()), title=SAMPLE_REPORT_TITLE)
        out.append(f"created sample report #{report.id} for dev@test.com "
                   f"({report.n_files} files, {report.n_medium} medium, {report.n_high} high)")
    return out
