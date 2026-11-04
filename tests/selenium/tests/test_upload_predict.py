"""Sample Selenium test 2 — upload the sample project ZIP, wait for the prediction,
and check the report (risk badges, ordering, sorting, drill-down, exports)."""
from pathlib import Path

from tests.selenium.pages import LoginPage, UploadPage

SAMPLE_ZIP = Path(__file__).resolve().parents[3] / "data" / "samples" / "sample_project.zip"


def test_upload_zip_and_view_prediction(driver, base_url, timeout):
    LoginPage(driver, base_url, timeout).login_as("dev@test.com")

    report = UploadPage(driver, base_url, timeout).open().upload_file(
        SAMPLE_ZIP, title="Selenium sample upload")

    assert report.is_done, report.flash_messages()
    assert report.title == "Selenium sample upload"
    assert report.summary()["files"] == "8"
    assert report.charts_rendered()

    # Ranked by probability: the long legacy function is the riskiest file.
    paths = report.file_paths()
    assert paths[0] == "legacy/report_builder.py"
    assert report.risk_of("legacy/report_builder.py") == "Medium"
    assert report.risk_of("inventory/utils.py") == "Low"
    probs = [report.probability_of(p) for p in paths]
    assert probs == sorted(probs, reverse=True)

    # Client-side sorting by file name.
    assert report.sort_by("file") == "file:ascending"
    assert report.file_paths() == sorted(paths)

    # Unit drill-down and export links.
    assert report.expand_units("inventory/pricing.py") == ["Low", "Low"]
    assert report.export_url("pdf").endswith(f"/reports/{report.report_id}/export.pdf")


def test_upload_unsupported_file_shows_error(driver, base_url, timeout, tmp_path):
    LoginPage(driver, base_url, timeout).login_as("dev@test.com")
    notes = tmp_path / "notes.txt"
    notes.write_text("not code")

    page = UploadPage(driver, base_url, timeout).open()
    page.select_file(notes)
    message = page.submit_expecting_error()

    assert "not a supported source file" in message
    assert page.current_path == "/upload"
