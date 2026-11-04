"""Application configuration, driven by environment variables / .env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _path(name: str, default: str) -> Path:
    p = Path(os.getenv(name, default))
    return p if p.is_absolute() else BASE_DIR / p


def _db_url(default_path: Path) -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        return f"sqlite:///{default_path.as_posix()}"
    prefix = "sqlite:///"
    if url.startswith(prefix) and not Path(url[len(prefix):]).is_absolute():
        return prefix + (BASE_DIR / url[len(prefix):]).as_posix()
    return url


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-change-me")
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", "5000"))

    INSTANCE_DIR = BASE_DIR / "instance"
    SQLALCHEMY_DATABASE_URI = _db_url(INSTANCE_DIR / "sdp.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_DIR = _path("UPLOAD_DIR", "instance/uploads")
    WORKSPACE_DIR = _path("WORKSPACE_DIR", "instance/workspaces")
    MODEL_DIR = _path("MODEL_DIR", "models")
    RAW_DATA_DIR = BASE_DIR / "data" / "raw"
    RESULTS_DIR = BASE_DIR / "docs" / "results"
    LOG_DIR = _path("LOG_DIR", "logs")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024
    MAX_REPO_MB = int(os.getenv("MAX_REPO_MB", "100"))  # extracted / cloned size cap
    MAX_FILES_PER_ANALYSIS = int(os.getenv("MAX_FILES_PER_ANALYSIS", "2000"))
    GIT_CLONE_TIMEOUT_SEC = int(os.getenv("GIT_CLONE_TIMEOUT_SEC", "60"))
    ALLOWED_GIT_HOSTS = [h.strip().lower() for h in
                         os.getenv("ALLOWED_GIT_HOSTS", "github.com,gitlab.com,bitbucket.org").split(",")
                         if h.strip()]

    RISK_MEDIUM_THRESHOLD = float(os.getenv("RISK_MEDIUM_THRESHOLD", "0.4"))
    RISK_HIGH_THRESHOLD = float(os.getenv("RISK_HIGH_THRESHOLD", "0.7"))
    # Exact SHAP is ~0.5 s/unit on the shipped forests; budget it per analysis.
    EXACT_SHAP_BUDGET_SEC = float(os.getenv("EXACT_SHAP_BUDGET_SEC", "15"))

    WTF_CSRF_ENABLED = True
    TESTING = False


class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    EXACT_SHAP_BUDGET_SEC = 2.0
