"""Evidence for the exam: save a screenshot after EVERY Selenium test (pass or fail)
into tests/selenium/artifacts/evidence/ and attach it to the pytest-html report."""
import uuid
from datetime import datetime
from pathlib import Path

import pytest

EVIDENCE = Path(__file__).resolve().parents[1] / "artifacts" / "evidence"


@pytest.fixture
def new_user(driver, base_url, timeout):
    """REUSABLE STEP: register a brand-new Developer account through the UI and return
    its email (password Passw0rd1). Ends on the login page, logged out."""
    from tests.selenium.pages import BasePage
    email = f"user_{uuid.uuid4().hex[:8]}@test.com"
    page = BasePage(driver, base_url, timeout)
    page.open("/register")
    page.wait_for("register-form")
    page.type("register-name-input", "Exam User")
    page.type("register-email-input", email)
    page.type("register-password-input", "Passw0rd1")
    page.type("register-confirm-input", "Passw0rd1")
    page.click("register-submit-btn")
    page.wait_for("login-form")
    return email


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or "driver" not in item.fixturenames:
        return
    driver = item.funcargs.get("driver")
    if driver is None:
        return
    status = "PASS" if report.passed else "FAIL"
    name = "".join(c if c.isalnum() or c in "-_" else "_" for c in item.name)[:100]
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    try:
        driver.save_screenshot(str(EVIDENCE / f"{status}_{name}_{datetime.now():%H%M%S}.png"))
        image = driver.get_screenshot_as_base64()
    except Exception:          # e.g. an alert is still open
        return
    html = item.config.pluginmanager.getplugin("html")
    if html is not None:       # pytest-html installed -> embed the screenshot in the report
        report.extras = getattr(report, "extras", []) + [html.extras.image(image, "Screenshot")]
