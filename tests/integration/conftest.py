import json
import os
import shutil
from pathlib import Path

import pytest

from config import BASE_DIR, TestConfig

PASSWORD = "Test@1234"


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    """Isolated app: temp DB / workspaces / logs; models dir mirrors the shipped models
    (hard links, so retrain tests never touch the real registry)."""
    from app import create_app
    from app.extensions import db
    from app.seed import seed_all

    tmp = tmp_path_factory.mktemp("sdp")
    model_dir = tmp / "models"
    model_dir.mkdir()
    real = BASE_DIR / "models"
    reg = json.loads((real / "registry.json").read_text())
    for level in reg.values():
        for v in level["versions"]:
            src, dst = real / v["file"], model_dir / v["file"]
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)
    shutil.copy2(real / "registry.json", model_dir / "registry.json")

    app = create_app(TestConfig, SQLALCHEMY_DATABASE_URI=f"sqlite:///{(tmp / 'test.db').as_posix()}",
                     INSTANCE_DIR=tmp, UPLOAD_DIR=tmp / "uploads", WORKSPACE_DIR=tmp / "ws",
                     LOG_DIR=tmp / "logs", MODEL_DIR=model_dir, EXACT_SHAP_BUDGET_SEC=1.0)
    app.config.update(TRAINING_SYNC=True, TRAINING_N_JOBS=1)
    with app.app_context():
        seed_all(with_report=True)
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, email, password=PASSWORD, follow=True):
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=follow)


@pytest.fixture
def dev(client):
    login(client, "dev@test.com")
    return client


@pytest.fixture
def qa(client):
    login(client, "qa@test.com")
    return client


@pytest.fixture
def admin(client):
    login(client, "admin@test.com")
    return client


SAMPLE = Path(__file__).resolve().parents[2] / "data" / "samples" / "sample_project"
