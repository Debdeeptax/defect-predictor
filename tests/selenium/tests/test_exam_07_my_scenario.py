"""EXAM SCENARIO 7 - WORKED EXAMPLE written from scratch with the 8-step recipe (Part G).

Scenario given by the examiner:
  "A Developer opens the upload page from the dashboard and finds a report through the
   reports list. A QA Engineer must not see the upload option."
"""
from tests.selenium.pages import LoginPage

PASSWORD = "Test@1234"


def test_TC_NEW_01_dashboard_button_opens_upload_page(driver, base_url, timeout):
    page = LoginPage(driver, base_url, timeout).login_as("dev@test.com", PASSWORD)   # precondition
    page.click("dashboard-analyze-btn")                                             # action
    page.wait_for("upload-form")                                                    # wait (sync)
    assert page.current_path == "/upload"                                           # verify
    assert page.text("upload-heading") == "Analyze code"


def test_TC_NEW_02_reports_list_opens_the_report(driver, base_url, timeout):
    page = LoginPage(driver, base_url, timeout).login_as("dev@test.com", PASSWORD)
    page.click("nav-reports")
    page.wait_for("reports-table")
    assert page.exists("report-list-row-1")
    page.click("report-link-1")
    page.wait_for("status-done")
    assert page.text("report-title") == "Sample project (seed)"


def test_TC_NEW_03_qa_does_not_see_upload(driver, base_url, timeout):
    page = LoginPage(driver, base_url, timeout).login_as("qa@test.com", PASSWORD)
    assert not page.exists("dashboard-analyze-btn")                                 # negative check
    assert "nav-upload" not in page.nav_items()
