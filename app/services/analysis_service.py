"""Analysis orchestration: CodeRepository -> MetricExtractor -> PredictionEngine -> Report row."""
from __future__ import annotations

import json
import logging
from typing import BinaryIO

from flask import current_app

from app.exceptions import SDPError
from app.extensions import db
from app.metrics.metric_extractor import MetricExtractor
from app.ml.ml_model import ModelNotAvailableError
from app.models import Report, ReportStatus, Submission, User
from app.models.user import utcnow
from app.services.audit_service import audit
from app.services.code_repository import CodeRepository, Workspace
from app.services.prediction_engine import PredictionEngine

log = logging.getLogger(__name__)


def get_engine() -> PredictionEngine:
    """One engine per app (models + SHAP explainers are cached inside it)."""
    ext = current_app.extensions
    if "prediction_engine" not in ext:
        ext["prediction_engine"] = PredictionEngine.from_config(current_app.config_obj)
    return ext["prediction_engine"]


def get_code_repository() -> CodeRepository:
    return CodeRepository.from_config(current_app.config_obj)


def analyse_upload(user: User, filename: str, stream: BinaryIO, title: str | None = None) -> Report:
    repo = get_code_repository()
    ws = repo.from_upload(filename, stream)  # raises SDPError on invalid input
    return _analyse(user, repo, ws, title)


def analyse_git(user: User, url: str, title: str | None = None) -> Report:
    repo = get_code_repository()
    ws = repo.from_git(url)
    return _analyse(user, repo, ws, title)


def _analyse(user: User, repo: CodeRepository, ws: Workspace, title: str | None) -> Report:
    sub = Submission(user_id=user.id, source_type=ws.source_type, source_name=ws.source_name,
                     meta_json=json.dumps(ws.meta))
    db.session.add(sub)
    db.session.flush()
    report = Report(submission_id=sub.id, user_id=user.id,
                    title=(title or "").strip()[:200] or _default_title(ws),
                    status=ReportStatus.RUNNING)
    db.session.add(report)
    db.session.commit()
    try:
        cfg = current_app.config_obj
        extraction = MetricExtractor(cfg.MAX_FILES_PER_ANALYSIS).extract(ws.path)
        payload = get_engine().predict(extraction)
        report.set_payload(payload)
        report.status = ReportStatus.DONE
        report.finished_at = utcnow()
        db.session.commit()
        s = payload["summary"]
        audit("analysis", f"report={report.id} source={ws.source_type}:{ws.source_name} "
                          f"files={s['files']} high={s['risk_counts']['High']}")
        return report
    except SDPError as exc:
        _fail(report, exc.user_message)
        raise
    except ModelNotAvailableError as exc:  # admin must train/activate a model; say so
        _fail(report, f"Prediction model unavailable: {exc}")
        raise
    except Exception as exc:
        log.exception("Analysis failed for report %s", report.id)
        _fail(report, "Unexpected error during analysis.")
        raise SDPError("Unexpected error during analysis. The administrator can find details "
                       "in the logs.") from exc
    finally:
        repo.cleanup(ws)


def _fail(report: Report, message: str) -> None:
    db.session.rollback()
    report.status = ReportStatus.FAILED
    report.error = message
    report.finished_at = utcnow()
    db.session.commit()
    audit("analysis_failed", f"report={report.id} error={message}")


def _default_title(ws: Workspace) -> str:
    name = ws.source_name.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name or "Analysis"
