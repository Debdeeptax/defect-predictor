"""EXAM SCENARIO 6 - GENERAL BROWSER SKILLS on this app: alerts, waits, navigation,
cookies/session, page title, keyboard, scrolling, element screenshot, access control."""
import pytest
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.selenium.pages import LoginPage, ReportPage


def test_TC_BR_01_javascript_alert(driver, base_url, timeout):
    """The app itself has no alerts, so we create one with JavaScript to practise handling it."""
    LoginPage(driver, base_url, timeout).open()
    driver.execute_script("setTimeout(() => alert('Session will expire soon'), 500)")
    alert = WebDriverWait(driver, 5).until(EC.alert_is_present())
    assert alert.text == "Session will expire soon"
    alert.accept()


def test_TC_BR_02_javascript_confirm_dismiss(driver, base_url, timeout):
    LoginPage(driver, base_url, timeout).open()
    driver.execute_script("setTimeout(() => window.answer = confirm('Delete report?'), 300)")
    WebDriverWait(driver, 5).until(EC.alert_is_present()).dismiss()     # click Cancel
    assert driver.execute_script("return window.answer") is False


def test_TC_BR_03_page_titles_and_back_forward(driver, base_url, timeout):
    page = LoginPage(driver, base_url, timeout).login_as("dev@test.com")
    assert "Dashboard" in driver.title
    page.click("nav-reports")
    page.wait_for("reports-heading")
    driver.back()                                                      # browser Back button
    page.wait_for("dashboard-heading")
    driver.forward()                                                   # browser Forward button
    page.wait_for("reports-heading")
    driver.refresh()
    assert page.exists("reports-heading")


def test_TC_BR_04_deleting_cookies_logs_user_out(driver, base_url, timeout):
    page = LoginPage(driver, base_url, timeout).login_as("dev@test.com")
    assert driver.get_cookie("session") is not None                   # Flask session cookie
    driver.delete_all_cookies()
    page.open("/dashboard")
    assert page.current_path.startswith("/login")                     # protected page -> login


def test_TC_BR_05_explicit_wait_timeout_demo(driver, base_url, timeout):
    """Waiting for something that never appears raises TimeoutException (a FAILED test in real use)."""
    LoginPage(driver, base_url, timeout).open()
    with pytest.raises(TimeoutException):
        WebDriverWait(driver, 2).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="dashboard-heading"]')))


def test_TC_BR_06_scroll_and_element_screenshot(driver, base_url, timeout, tmp_path):
    LoginPage(driver, base_url, timeout).login_as("dev@test.com")
    report = ReportPage(driver, base_url, timeout).open_report(1)
    table = report.find("report-table")
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", table)
    shot = tmp_path / "table.png"
    assert table.screenshot(str(shot))                                 # screenshot of ONE element
    assert shot.stat().st_size > 1000


@pytest.mark.parametrize("email, path, expected", [
    ("dev@test.com", "/admin/users", "403"),
    ("qa@test.com", "/upload", "403"),
    ("admin@test.com", "/admin/users", None),
], ids=["TC_BR_07_dev_blocked_from_admin", "TC_BR_08_qa_blocked_from_upload", "TC_BR_09_admin_allowed"])
def test_role_based_access(driver, base_url, timeout, email, path, expected):
    page = LoginPage(driver, base_url, timeout).login_as(email)
    page.open(path)
    assert page.error_code == expected
