import io
import re

import numpy as np
import pandas as pd
import pytest

from tests.integration.conftest import PASSWORD, SAMPLE, login


def collect_testids(html: str) -> set[str]:
    return set(re.findall(r'data-testid="([^"]+)"', html))


def upload(client, filename, data: bytes, title="t", follow=True):
    return client.post("/upload", data={"source": "file", "title": title,
                                        "file": (io.BytesIO(data), filename)},
                       content_type="multipart/form-data", follow_redirects=follow)


# ---------------------------------------------------------------------- health & auth
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok" and body["database"] is True
    assert body["models"]["function"].startswith("function_v1")


def test_anonymous_is_redirected_to_login(client):
    r = client.get("/dashboard")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_login_failure_shows_flash_error(client):
    r = login(client, "dev@test.com", "wrong-pass1")
    assert "flash-error" in collect_testids(r.get_data(as_text=True))
    assert "Invalid email or password" in r.get_data(as_text=True)


def test_login_logout_roundtrip(client):
    r = login(client, "dev@test.com")
    html = r.get_data(as_text=True)
    assert 'data-testid="dashboard-heading"' in html and 'data-role="developer"' in html
    r = client.post("/logout", follow_redirects=True)
    assert "login-heading" in collect_testids(r.get_data(as_text=True))


def test_open_redirect_blocked(client):
    r = client.post("/login?next=https://evil.example/x",
                    data={"email": "dev@test.com", "password": PASSWORD})
    assert r.headers["Location"].endswith("/dashboard")


def test_register_creates_developer_and_validates(client, app):
    r = client.post("/register", data={"name": "New Dev", "email": "new@test.com",
                                       "password": "abc12345", "confirm": "abc12345"},
                    follow_redirects=True)
    assert "Account created" in r.get_data(as_text=True)
    r = login(client, "new@test.com", "abc12345")
    assert 'data-role="developer"' in r.get_data(as_text=True)
    client.post("/logout")
    dup = client.post("/register", data={"name": "X", "email": "new@test.com",
                                         "password": "abc12345", "confirm": "abc12345"})
    assert "already exists" in dup.get_data(as_text=True)
    weak = client.post("/register", data={"name": "X", "email": "weak@test.com",
                                          "password": "abcdefgh", "confirm": "abcdefgh"})
    assert "letters and digits" in weak.get_data(as_text=True)


# ---------------------------------------------------------------------- role access
@pytest.mark.parametrize("who,url,code", [
    ("dev@test.com", "/upload", 200), ("dev@test.com", "/reports/compare", 403),
    ("dev@test.com", "/admin/models", 403), ("dev@test.com", "/admin/users", 403),
    ("qa@test.com", "/upload", 403), ("qa@test.com", "/reports/compare", 200),
    ("qa@test.com", "/admin/logs", 403),
    ("admin@test.com", "/upload", 200), ("admin@test.com", "/admin/models", 200),
    ("admin@test.com", "/admin/users", 200), ("admin@test.com", "/admin/logs", 200),
])
def test_role_access_matrix(client, who, url, code):
    login(client, who)
    r = client.get(url)
    assert r.status_code == code
    if code == 403:
        assert "error-code" in collect_testids(r.get_data(as_text=True))


def test_nav_reflects_role(client):
    html = login(client, "qa@test.com").get_data(as_text=True)
    ids = collect_testids(html)
    assert {"nav-reports", "nav-compare"} <= ids and "nav-upload" not in ids and "nav-admin-models" not in ids


# ---------------------------------------------------------------------- analysis
def test_upload_single_file_produces_report(dev):
    code = (SAMPLE / "inventory" / "pricing.py").read_bytes()
    r = upload(dev, "pricing.py", code, title="Pricing only")
    html = r.get_data(as_text=True)
    ids = collect_testids(html)
    assert "status-done" in ids and "report-table" in ids
    assert "risk-badge-pricing-py" in ids and "export-pdf-btn" in ids
    assert "Pricing only" in html


def test_upload_zip_and_exports(dev, app):
    from app.seed import sample_zip_bytes
    r = upload(dev, "sample.zip", sample_zip_bytes(), title="Zip run", follow=False)
    assert r.status_code == 302
    report_url = r.headers["Location"]
    html = dev.get(report_url).get_data(as_text=True)
    ids = collect_testids(html)
    assert "risk-badge-legacy-report-builder-py" in ids
    assert 'id="summary-files" data-testid="summary-files">8<' in html
    rid = report_url.rstrip("/").split("/")[-1]
    csv = dev.get(f"/reports/{rid}/export.csv")
    assert csv.mimetype == "text/csv" and csv.get_data(as_text=True).startswith("rank,file")
    units = dev.get(f"/reports/{rid}/export.csv?level=unit")
    assert units.get_data(as_text=True).startswith("file,level,unit")
    pdf = dev.get(f"/reports/{rid}/export.pdf")
    assert pdf.mimetype == "application/pdf" and pdf.data.startswith(b"%PDF")
    assert "attachment" in pdf.headers["Content-Disposition"]


@pytest.mark.parametrize("filename,data,message", [
    ("notes.txt", b"hello", "not a supported source file"),
    ("empty.py", b"", "empty"),
    ("broken.zip", b"PK\x03\x04junk", "corrupt"),
    ("only_text.zip", None, "supported language"),
    ("bad.py", b"def f(:\n", "could be parsed"),
])
def test_upload_errors_are_flashed(dev, filename, data, message):
    if data is None:
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("README.md", "# hi")
        data = buf.getvalue()
    r = upload(dev, filename, data)
    html = r.get_data(as_text=True)
    assert "flash-error" in collect_testids(html), html[:500]
    assert message in html


def test_upload_without_file_and_bad_git(dev):
    r = dev.post("/upload", data={"source": "file"}, follow_redirects=True)
    assert "Please choose a file" in r.get_data(as_text=True)
    r = dev.post("/upload", data={"source": "git", "git_url": "https://evil.example.com/a/b"},
                 follow_redirects=True)
    assert "is not allowed" in r.get_data(as_text=True)


def test_report_visibility(client, app):
    from app.extensions import db
    from app.models import Report
    with app.app_context():
        seed_report = db.session.scalar(db.select(Report).filter_by(title="Sample project (seed)"))
        rid = seed_report.id
    client.post("/register", data={"name": "Other", "email": "other@test.com",
                                   "password": "abc12345", "confirm": "abc12345"})
    login(client, "other@test.com", "abc12345")
    assert client.get(f"/reports/{rid}").status_code == 403
    assert client.get(f"/reports/{rid}/export.pdf").status_code == 403
    assert f"report-list-row-{rid}" not in collect_testids(client.get("/reports").get_data(as_text=True))
    client.post("/logout")
    login(client, "qa@test.com")
    assert client.get(f"/reports/{rid}").status_code == 200
    assert f"report-list-row-{rid}" in collect_testids(client.get("/reports").get_data(as_text=True))
    assert client.get("/reports/99999").status_code == 404


def test_compare_runs(qa, app):
    from app.extensions import db
    from app.models import Report
    with app.app_context():
        ids = [r.id for r in db.session.scalars(db.select(Report).filter_by(status="done")
                                                .order_by(Report.id)).all()]
    assert len(ids) >= 2
    r = qa.get(f"/reports/compare?a={ids[0]}&b={ids[1]}")
    html = r.get_data(as_text=True)
    assert "status-done" in collect_testids(html) and "compare-table" in collect_testids(html)
    same = qa.get(f"/reports/compare?a={ids[0]}&b={ids[0]}")
    assert "two different reports" in same.get_data(as_text=True)


# ---------------------------------------------------------------------- admin
def test_admin_role_change_and_self_protection(admin, app):
    admin.post("/register")  # no-op while logged in (redirect)
    r = admin.post("/admin/users/2/role", data={"role": "admin"}, follow_redirects=True)  # qa -> admin
    assert "is now Admin" in r.get_data(as_text=True)
    admin.post("/admin/users/2/role", data={"role": "qa"})
    from app.extensions import db
    from app.models import User
    with app.app_context():
        me = db.session.scalar(db.select(User).filter_by(email="admin@test.com"))
        my_id = me.id
    r = admin.post(f"/admin/users/{my_id}/role", data={"role": "developer"}, follow_redirects=True)
    assert "cannot remove your own admin role" in r.get_data(as_text=True)
    r = admin.post(f"/admin/users/{my_id}/toggle", follow_redirects=True)
    assert "cannot deactivate your own account" in r.get_data(as_text=True)


def test_deactivated_user_cannot_login(client, app):
    client.post("/register", data={"name": "Temp", "email": "temp@test.com",
                                   "password": "abc12345", "confirm": "abc12345"})
    from app.extensions import db
    from app.models import User
    with app.app_context():
        uid = db.session.scalar(db.select(User).filter_by(email="temp@test.com")).id
    login(client, "admin@test.com")
    client.post(f"/admin/users/{uid}/toggle")
    client.post("/logout")
    r = login(client, "temp@test.com", "abc12345")
    assert "deactivated" in r.get_data(as_text=True)


def test_retrain_with_csv_then_switch_back(admin, app):
    rng = np.random.default_rng(0)
    n = 300
    df = pd.DataFrame({c: rng.integers(1, 30, n) for c in
                       ["wmc", "dit", "noc", "cbo", "rfc", "lcom", "max_cc", "ce", "npm"]})
    df["loc"] = rng.integers(10, 2000, n)
    df["avg_cc"] = rng.random(n) * 4
    df["amc"] = df["loc"] / df["wmc"]
    df["lcom3"] = rng.random(n) * 2
    df["bug"] = (df["loc"] + rng.normal(0, 300, n) > 1100).astype(int)
    r = admin.post("/admin/models/retrain",
                   data={"level": "class", "preset": "quick", "activate": "y",
                         "data": (io.BytesIO(df.to_csv(index=False).encode()), "synthetic.csv")},
                   content_type="multipart/form-data", follow_redirects=True)
    html = r.get_data(as_text=True)
    ids = collect_testids(html)
    assert "status-done" in ids, html[-1500:]
    assert "job-summary-table" in ids
    models_page = admin.get("/admin/models").get_data(as_text=True)
    assert 'data-testid="active-badge-class" data-version="2"' in models_page
    r = admin.post("/admin/models/activate", data={"level": "class", "file": _v1_file(app, "class")},
                   follow_redirects=True)
    assert 'data-testid="active-badge-class" data-version="1"' in r.get_data(as_text=True)


def test_retrain_rejects_bad_csv(admin):
    r = admin.post("/admin/models/retrain",
                   data={"level": "function", "preset": "quick",
                         "data": (io.BytesIO(b"a,b\n1,2\n"), "bad.csv")},
                   content_type="multipart/form-data", follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "status-failed" in collect_testids(html) and "Missing function-level columns" in html


def test_logs_page_shows_audit(admin):
    html = admin.get("/admin/logs?action=login").get_data(as_text=True)
    assert "audit-table" in collect_testids(html) and 'data-action="login"' in html


def test_404_page(dev):
    r = dev.get("/no-such-page")
    assert r.status_code == 404 and "error-code" in collect_testids(r.get_data(as_text=True))


def _v1_file(app, level):
    from app.ml.registry import ModelRegistry
    return next(v["file"] for v in ModelRegistry(app.config_obj.MODEL_DIR).list_versions(level)
                if v["version"] == 1)
