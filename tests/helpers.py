"""Shared test helpers: an isolated, seeded app instance (temp DB / workspace / logs,
models dir mirroring the shipped models via hard links)."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from config import BASE_DIR, TestConfig

PASSWORD = "Test@1234"
SAMPLE_DIR = BASE_DIR / "data" / "samples" / "sample_project"


def mirror_models(dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    real = BASE_DIR / "models"
    reg = json.loads((real / "registry.json").read_text())
    for level in reg.values():
        for v in level["versions"]:
            src, dst = real / v["file"], dest / v["file"]
            if dst.exists():
                continue
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)
    shutil.copy2(real / "registry.json", dest / "registry.json")
    return dest


def build_test_app(tmp: Path, *, seed: bool = True, csrf: bool = False, **overrides):
    """Create a fully isolated app under `tmp` and (optionally) seed it."""
    from app import create_app
    from app.seed import seed_all

    tmp = Path(tmp)
    settings = dict(SQLALCHEMY_DATABASE_URI=f"sqlite:///{(tmp / 'test.db').as_posix()}",
                    INSTANCE_DIR=tmp, UPLOAD_DIR=tmp / "uploads", WORKSPACE_DIR=tmp / "ws",
                    LOG_DIR=tmp / "logs", MODEL_DIR=mirror_models(tmp / "models"),
                    EXACT_SHAP_BUDGET_SEC=1.0, WTF_CSRF_ENABLED=csrf)
    settings.update(overrides)
    app = create_app(TestConfig, **settings)
    app.config.update(TRAINING_SYNC=True, TRAINING_N_JOBS=1)
    if seed:
        with app.app_context():
            seed_all(with_report=True)
    return app
