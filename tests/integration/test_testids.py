"""Selenium-readiness audit: every interactive element on every page must carry a kebab-case
`data-testid` and a page-unique `id`. Renders each page per role and parses the HTML."""
import io
import re
from html.parser import HTMLParser

import pytest

from tests.integration.conftest import login

KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
INTERACTIVE = {"a", "button", "select", "textarea", "summary"}


class Audit(HTMLParser):
    def __init__(self):
        super().__init__()
        self.thead = 0
        self.tbody = 0
        self.problems: list[str] = []
        self.ids: dict[str, int] = {}
        self.testids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids[a["id"]] = self.ids.get(a["id"], 0) + 1
        if "data-testid" in a:
            self.testids.add(a["data-testid"])
            if not KEBAB.match(a["data-testid"]):
                self.problems.append(f"non-kebab data-testid {a['data-testid']!r} on <{tag}>")
        if tag == "thead":
            self.thead += 1
        elif tag == "tbody":
            self.tbody += 1
        needs = (
            tag in INTERACTIVE
            or (tag == "input" and a.get("type") != "hidden")
            or (tag == "tr" and self.tbody and not self.thead)
            or (tag == "div" and "alert" in (a.get("class") or "").split())
        )
        if needs:
            missing = [k for k in ("id", "data-testid") if not a.get(k)]
            if missing:
                desc = a.get("class") or a.get("name") or a.get("href") or ""
                self.problems.append(f"<{tag} {desc[:40]!r}> missing {', '.join(missing)}")

    def handle_endtag(self, tag):
        if tag == "thead":
            self.thead -= 1
        elif tag == "tbody":
            self.tbody -= 1

    def report(self):
        dupes = [i for i, n in self.ids.items() if n > 1]
        return self.problems + [f"duplicate id {d!r}" for d in dupes]


def audit(html: str) -> Audit:
    p = Audit()
    p.feed(html)
    return p


@pytest.fixture(scope="module")
def pages(app):
    """Render every page as the relevant role -> {name: html}."""
    from app.extensions import db
    from app.models import Report, TrainingJob
    from app.seed import sample_zip_bytes

    out = {}
    c = app.test_client()
    out["login"] = c.get("/login").get_data(as_text=True)
    out["register"] = c.get("/register").get_data(as_text=True)
    out["login-failed-flash"] = login(c, "dev@test.com", "wrong-pass1").get_data(as_text=True)
    out["404-anon"] = c.get("/nope").get_data(as_text=True)

    login(c, "dev@test.com")
    r = c.post("/upload", data={"source": "file", "title": "audit run",
                                "file": (io.BytesIO(sample_zip_bytes()), "s.zip")},
               content_type="multipart/form-data", follow_redirects=True)
    out["report-detail+flash"] = r.get_data(as_text=True)
    out["dashboard-dev"] = c.get("/dashboard").get_data(as_text=True)
    out["upload"] = c.get("/upload").get_data(as_text=True)
    out["reports-dev"] = c.get("/reports").get_data(as_text=True)
    out["403"] = c.get("/admin/models").get_data(as_text=True)
    c.post("/logout")

    with app.app_context():
        ids = [x.id for x in db.session.scalars(db.select(Report).filter_by(status="done")
                                                 .order_by(Report.id)).all()]
    login(c, "qa@test.com")
    out["dashboard-qa"] = c.get("/dashboard").get_data(as_text=True)
    out["reports-qa"] = c.get("/reports").get_data(as_text=True)
    out["compare-form"] = c.get("/reports/compare").get_data(as_text=True)
    out["compare-result"] = c.get(f"/reports/compare?a={ids[0]}&b={ids[-1]}").get_data(as_text=True)
    c.post("/logout")

    login(c, "admin@test.com")
    c.post("/admin/models/retrain", data={"level": "class", "preset": "quick",
                                          "data": (io.BytesIO(b"a,b\n1,2\n"), "bad.csv")},
           content_type="multipart/form-data")
    with app.app_context():
        job_id = db.session.scalar(db.select(TrainingJob.id).order_by(TrainingJob.id.desc()))
    out["admin-dashboard"] = c.get("/dashboard").get_data(as_text=True)
    out["admin-users"] = c.get("/admin/users").get_data(as_text=True)
    out["admin-models"] = c.get("/admin/models").get_data(as_text=True)
    out["admin-job"] = c.get(f"/admin/models/jobs/{job_id}").get_data(as_text=True)
    out["admin-logs"] = c.get("/admin/logs").get_data(as_text=True)
    out["admin-logs-filtered"] = c.get("/admin/logs?action=nothing-matches").get_data(as_text=True)
    return out


PAGE_NAMES = ["login", "register", "login-failed-flash", "404-anon", "report-detail+flash",
              "dashboard-dev", "upload", "reports-dev", "403", "dashboard-qa", "reports-qa",
              "compare-form", "compare-result", "admin-dashboard", "admin-users", "admin-models",
              "admin-job", "admin-logs", "admin-logs-filtered"]


@pytest.mark.parametrize("name", PAGE_NAMES)
def test_every_interactive_element_has_testid_and_unique_id(pages, name):
    problems = audit(pages[name]).report()
    assert not problems, f"{name}:\n  " + "\n  ".join(problems)


@pytest.mark.parametrize("name,expected", [
    ("login-failed-flash", {"flash-error", "login-email-input", "login-submit-btn"}),
    ("report-detail+flash", {"flash-success", "status-done", "report-table", "risk-chart",
                             "risk-badge-legacy-report-builder-py", "export-pdf-btn"}),
    ("compare-result", {"status-done", "compare-table"}),
    ("admin-job", {"status-failed", "job-status", "job-error"}),
    ("403", {"error-code"}),
])
def test_key_sync_markers_present(pages, name, expected):
    assert expected <= audit(pages[name]).testids
