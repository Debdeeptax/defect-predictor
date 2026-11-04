"""Admin-triggered retraining in a background thread, tracked as a TrainingJob row."""
from __future__ import annotations

import json
import logging
import threading
import uuid
from pathlib import Path

from flask import Flask, current_app
from werkzeug.datastructures import FileStorage

from app.exceptions import SDPError
from app.extensions import db
from app.ml.features import LEVELS
from app.ml.registry import ModelRegistry
from app.ml.trainer import Trainer
from app.models import JobStatus, TrainingJob, User
from app.models.user import utcnow
from app.services.audit_service import audit

log = logging.getLogger(__name__)

CV_PRESETS = {"quick": (3, 1), "standard": (5, 5)}
MAX_CSV_BYTES = 20 * 1024 * 1024


class TrainingError(SDPError):
    user_message = "Could not start training."


def registry() -> ModelRegistry:
    return ModelRegistry(current_app.config_obj.MODEL_DIR)


def active_job() -> TrainingJob | None:
    return db.session.scalar(db.select(TrainingJob)
                             .where(TrainingJob.status.in_(JobStatus.ACTIVE))
                             .order_by(TrainingJob.id.desc()))


def start_training(user: User, level: str, preset: str, activate: bool,
                   csv_file: FileStorage | None = None) -> TrainingJob:
    if level not in LEVELS:
        raise TrainingError("Unknown model level.")
    if preset not in CV_PRESETS:
        raise TrainingError("Unknown CV preset.")
    if active_job() is not None:
        raise TrainingError("Another training job is already running. Wait for it to finish.")

    cfg = current_app.config_obj
    csv_path = None
    source = "builtin"
    if csv_file is not None and csv_file.filename:
        if not csv_file.filename.lower().endswith(".csv"):
            raise TrainingError("Training data must be a .csv file.")
        data = csv_file.read(MAX_CSV_BYTES + 1)
        if len(data) > MAX_CSV_BYTES or not data:
            raise TrainingError("CSV is empty or larger than 20 MB.")
        upload_dir = Path(cfg.UPLOAD_DIR) / "training"
        upload_dir.mkdir(parents=True, exist_ok=True)
        csv_path = upload_dir / f"{uuid.uuid4().hex[:8]}_{Path(csv_file.filename).name}"
        csv_path.write_bytes(data)
        source = csv_file.filename

    folds, repeats = CV_PRESETS[preset]
    job = TrainingJob(level=level, source=source, folds=folds, repeats=repeats,
                      activate=activate, started_by_id=user.id)
    db.session.add(job)
    db.session.commit()
    audit("retrain_start", f"job={job.id} level={level} source={source} cv={folds}x{repeats}")

    app = current_app._get_current_object()
    if app.config.get("TRAINING_SYNC"):  # tests: run inline for determinism
        _run(app, job.id, csv_path)
    else:
        threading.Thread(target=_run, args=(app, job.id, csv_path), daemon=True,
                         name=f"train-{job.id}").start()
    return job


def _run(app: Flask, job_id: int, csv_path: Path | None) -> None:
    with app.app_context():
        job = db.session.get(TrainingJob, job_id)
        job.status = JobStatus.RUNNING
        db.session.commit()
        lines: list[str] = []

        def progress(msg: str) -> None:
            lines.append(msg)
            job.log = "\n".join(lines)
            db.session.commit()

        cfg = app.config_obj
        try:
            trainer = Trainer(job.level, model_dir=cfg.MODEL_DIR,
                              results_dir=Path(cfg.INSTANCE_DIR) / "training_results" / str(job.id),
                              folds=job.folds, repeats=job.repeats,
                              n_jobs=app.config.get("TRAINING_N_JOBS", -1), progress=progress)
            result = trainer.run(raw_dir=cfg.RAW_DATA_DIR, csv_path=csv_path, save=True,
                                 activate=job.activate)
            meta = result.metadata
            job.result_json = json.dumps({
                "file": meta.get("file"), "version": meta.get("version"),
                "display_name": meta.get("display_name"), "best": result.best_key,
                "cv_auc": meta["cv"]["metrics"]["roc_auc"], "activated": job.activate,
                "summary": result.summary.round(4).reset_index().to_dict(orient="records"),
            })
            job.status = JobStatus.DONE
            audit("retrain_done", f"job={job.id} model={meta.get('file')} "
                                  f"auc={meta['cv']['metrics']['roc_auc']['mean']:.3f}",
                  user_id=job.started_by_id)
        except Exception as exc:  # report any failure on the job page
            log.exception("Training job %s failed", job_id)
            db.session.rollback()
            job = db.session.get(TrainingJob, job_id)
            job.status = JobStatus.FAILED
            job.error = getattr(exc, "user_message", None) or f"{type(exc).__name__}: {exc}"
            audit("retrain_failed", f"job={job_id} error={job.error}", user_id=job.started_by_id,
                  commit=False)
        finally:
            job.finished_at = utcnow()
            db.session.commit()
            if csv_path is not None:
                csv_path.unlink(missing_ok=True)


def activate_model(user: User, level: str, file: str) -> None:
    if level not in LEVELS:
        raise TrainingError("Unknown model level.")
    registry().activate(level, file)
    audit("model_activate", f"level={level} file={file}")
