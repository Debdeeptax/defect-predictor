from flask import Blueprint, current_app, jsonify
from sqlalchemy import text

from app.extensions import db
from app.ml.registry import ModelRegistry

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    try:
        db.session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    reg = ModelRegistry(current_app.config_obj.MODEL_DIR)
    models = {}
    for level in ("function", "class"):
        f = reg.active_file(level)
        models[level] = f if f and (reg.model_dir / f).exists() else None
    ok = db_ok and models["function"] is not None
    return jsonify({"status": "ok" if ok else "degraded", "database": db_ok,
                    "models": models}), (200 if ok else 503)
