import copy
import csv
import io

from app.services.report_service import FILE_CSV_COLUMNS, UNIT_CSV_COLUMNS, ReportService


def test_file_csv(sample_payload):
    rows = list(csv.DictReader(io.StringIO(ReportService.to_csv(sample_payload))))
    assert list(rows[0]) == FILE_CSV_COLUMNS
    assert len(rows) == len(sample_payload["files"])
    assert rows[0]["file"] == sample_payload["files"][0]["path"]
    assert rows[0]["top_metric_1"]


def test_unit_csv(sample_payload):
    rows = list(csv.DictReader(io.StringIO(ReportService.to_csv(sample_payload, "unit"))))
    assert list(rows[0]) == UNIT_CSV_COLUMNS
    assert len(rows) == sample_payload["summary"]["units"]


def test_pdf_renders_with_markup_like_text(sample_payload):
    p = copy.deepcopy(sample_payload)
    p["files"][0]["path"] = "weird/<b>&'name\".py"
    pdf = ReportService.to_pdf(p, title="Report for <repo> & co", source="x<y>.zip",
                               author="dev@test.com", report_id=7)
    assert pdf.startswith(b"%PDF") and len(pdf) > 2000


def _payload(files):
    counts = {"High": 0, "Medium": 0, "Low": 0}
    for _, _, r in files:
        counts[r] += 1
    return {"files": [{"path": p, "probability": pr, "risk": r} for p, pr, r in files],
            "summary": {"risk_counts": counts}}


def test_compare_runs():
    a = _payload([("a.py", 0.30, "Low"), ("b.py", 0.75, "High"), ("gone.py", 0.1, "Low")])
    b = _payload([("a.py", 0.55, "Medium"), ("b.py", 0.50, "Medium"), ("new.py", 0.2, "Low")])
    c = ReportService.compare(a, b)
    by = {r["path"]: r for r in c["rows"]}
    assert by["a.py"]["risk_change"] == "worse" and by["a.py"]["delta"] == 0.25
    assert by["b.py"]["risk_change"] == "better" and by["b.py"]["delta"] == -0.25
    assert by["gone.py"]["status"] == "removed" and by["new.py"]["status"] == "added"
    s = c["summary"]
    assert (s["common"], s["added"], s["removed"], s["worse"], s["better"]) == (2, 1, 1, 1, 1)
    assert s["mean_delta"] == 0.0
