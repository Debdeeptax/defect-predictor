"""EXAM SCENARIO 3 - FILE UPLOAD + PREDICTION (positive and negative)."""
from pathlib import Path

import pytest

from tests.selenium.pages import LoginPage, UploadPage

ROOT = Path(__file__).resolve().parents[3]
SAMPLE_ZIP = ROOT / "data" / "samples" / "sample_project.zip"
SINGLE_FILE = ROOT / "data" / "samples" / "sample_project" / "inventory" / "pricing.py"


@pytest.fixture
def upload_page(driver, base_url, timeout):
    LoginPage(driver, base_url, timeout).login_as("dev@test.com")   # precondition: logged in
    return UploadPage(driver, base_url, timeout).open()


def test_TC_UPL_01_upload_zip_shows_ranked_report(upload_page):
    report = upload_page.upload_file(SAMPLE_ZIP, title="Exam ZIP upload")
    assert report.is_done
    assert report.title == "Exam ZIP upload"
    assert "Analysis complete: 8 file(s) analysed." in report.flash_messages("success")
    summary = report.summary()
    assert summary["files"] == "8"
    assert int(summary["high"]) + int(summary["medium"]) + int(summary["low"]) == 8
    assert report.file_paths()[0] == "legacy/report_builder.py"     # riskiest file first


def test_TC_UPL_02_upload_single_python_file(upload_page):
    report = upload_page.upload_file(SINGLE_FILE)
    assert report.is_done
    assert report.summary()["files"] == "1"
    assert report.file_paths() == ["pricing.py"]


def test_TC_UPL_03_unsupported_file_type(upload_page, tmp_path):
    notes = tmp_path / "notes.txt"
    notes.write_text("this is not source code")
    upload_page.select_file(notes)
    message = upload_page.submit_expecting_error()
    assert message == "'notes.txt' is not a supported source file. Upload a source file or a .zip archive."
    assert upload_page.current_path == "/upload"


def test_TC_UPL_04_empty_file(upload_page, tmp_path):
    empty = tmp_path / "empty.py"
    empty.write_text("")
    upload_page.select_file(empty)
    assert upload_page.submit_expecting_error() == "The uploaded file is empty."


def test_TC_UPL_05_no_file_chosen(upload_page):
    assert upload_page.submit_expecting_error() == "Please choose a file to upload."


def test_TC_UPL_06_git_host_not_allowed(upload_page):
    upload_page.choose_git_source()
    upload_page.type("git-url-input", "https://example.com/owner/repo")
    message = upload_page.submit_expecting_error()
    assert message.startswith("Host 'example.com' is not allowed.")


def test_TC_UPL_07_git_url_empty(upload_page):
    upload_page.choose_git_source()
    assert upload_page.submit_expecting_error() == "Please enter a Git repository URL."
