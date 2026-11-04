"""App-level behaviour outside the main flows: CLI commands, error handlers, CSRF,
missing models, unexpected analysis failures. Each test builds its own isolated app."""
import io

import pytest

from tests.helpers import PASSWORD, build_test_app


def login(client, email="dev@test.com"):
    return client.post("/login", data={"email": email, "password": PASSWORD}, follow_redirects=True)


@pytest.fixture
def fresh_app(tmp_path):
    return build_test_app(tmp_path, seed=False)


def test_cli_init_seed_reset(fresh_app):
    runner = fresh_app.test_cli_runner()
    assert "tables created" in runner.invoke(args=["init-db"]).output
    out = runner.invoke(args=["seed"]).output
    assert "created developer dev@test.com" in out and "sample report #1" in out
    assert "exists  developer dev@test.com" in runner.invoke(args=["seed"]).output   # idempotent
    out = runner.invoke(args=["reset-db", "--no-seed"]).output
    assert "Database reset." in out
    from app.extensions import db
    from app.models import User
    with fresh_app.app_context():
        assert db.session.scalar(db.select(db.func.count(User.id))) == 0


def test_csrf_failure_is_friendly(tmp_path):
    app = build_test_app(tmp_path, seed=True, csrf=True)
    c = app.test_client()
    r = c.post("/login", data={"email": "dev@test.com", "password": PASSWORD}, follow_redirects=True)
    assert "Your session expired" in r.get_data(as_text=True)


def test_upload_too_large_is_flashed(tmp_path):
    app = build_test_app(tmp_path, seed=True)
    app.config["MAX_CONTENT_LENGTH"] = 2_000
    c = app.test_client()
    login(c)
    r = c.post("/upload", data={"source": "file", "file": (io.BytesIO(b"x = 1\n" * 1000), "big.py")},
               content_type="multipart/form-data", headers={"Referer": "/upload"}, follow_redirects=True)
    assert "larger than the" in r.get_data(as_text=True)


def test_unhandled_error_renders_500_page(tmp_path):
    app = build_test_app(tmp_path, seed=False)
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    r = app.test_client().get("/boom")
    assert r.status_code == 500 and 'data-testid="error-code">500<' in r.get_data(as_text=True)


def test_missing_models_degrade_health_and_upload(tmp_path):
    empty = tmp_path / "no-models"
    empty.mkdir()
    app = build_test_app(tmp_path, seed=False, MODEL_DIR=empty)
    with app.app_context():
        from app.seed import seed_all
        seed_all(with_report=False)
    c = app.test_client()
    h = c.get("/health")
    assert h.status_code == 503 and h.get_json()["status"] == "degraded"
    login(c)
    dash = c.get("/dashboard").get_data(as_text=True)
    assert 'data-testid="model-missing-function"' in dash
    r = c.post("/upload", data={"source": "file", "file": (io.BytesIO(b"def f():\n    return 1\n"), "a.py")},
               content_type="multipart/form-data", follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "Prediction model unavailable" in html
    from app.extensions import db
    from app.models import Report
    with app.app_context():
        rep = db.session.scalar(db.select(Report))
        assert rep.status == "failed"


def test_unexpected_analysis_error_marks_report_failed(tmp_path):
    app = build_test_app(tmp_path, seed=True)

    class Broken:
        def predict(self, _extraction):
            raise RuntimeError("model exploded")

        def model_info(self):
            return {"function": None, "class": None}

    app.extensions["prediction_engine"] = Broken()
    c = app.test_client()
    login(c)
    r = c.post("/upload", data={"source": "file", "title": "will fail",
                                "file": (io.BytesIO(b"def f():\n    return 1\n"), "a.py")},
               content_type="multipart/form-data", follow_redirects=True)
    assert "Unexpected error during analysis" in r.get_data(as_text=True)
    from app.extensions import db
    from app.models import Report
    with app.app_context():
        rep = db.session.scalar(db.select(Report).filter_by(title="will fail"))
        assert rep.status == "failed" and rep.error
        rid = rep.id
    page = c.get(f"/reports/{rid}").get_data(as_text=True)
    assert 'data-testid="status-failed"' in page and 'data-testid="report-error"' in page
    assert c.get(f"/reports/{rid}/export.pdf", follow_redirects=True).status_code == 200  # redirected back


def test_admin_activate_unknown_version(tmp_path):
    app = build_test_app(tmp_path, seed=False)
    with app.app_context():
        from app.seed import seed_all
        seed_all(with_report=False)
    c = app.test_client()
    login(c, "admin@test.com")
    r = c.post("/admin/models/activate", data={"level": "function", "file": "nope.joblib"},
               follow_redirects=True)
    assert "No function model version" in r.get_data(as_text=True)
    r = c.post("/admin/models/activate", data={"level": "weird", "file": "x"}, follow_redirects=True)
    assert "Unknown model level" in r.get_data(as_text=True)
