"""EXAM SCENARIO 1 - LOGIN (positive, negative, empty, invalid format).
Data-driven: the rows come from tests/selenium/data/login_data.csv."""
import csv
from pathlib import Path

import pytest
from selenium.webdriver.common.keys import Keys

from tests.selenium.pages import LoginPage

DATA = Path(__file__).resolve().parents[1] / "data" / "login_data.csv"


def load_rows():
    with open(DATA, newline="", encoding="utf-8") as f:
        return [pytest.param(r["email"], r["password"], r["expected_result"], r["expected_message"],
                             id=r["case_id"]) for r in csv.DictReader(f)]


@pytest.mark.parametrize("email, password, expected_result, expected_message", load_rows())
def test_login_data_driven(driver, base_url, timeout, email, password, expected_result, expected_message):
    page = LoginPage(driver, base_url, timeout).open()          # 1. open the login page
    page.login(email, password)                                 # 2. type + click Login
    if expected_result == "success":                            # 3. verify
        assert page.current_path == "/dashboard"
        assert page.exists("dashboard-heading")
        assert page.user_role == expected_message               # role badge: developer / qa / admin
    else:
        assert page.error_message == expected_message
        assert not page.is_logged_in
        assert page.exists("login-form")


@pytest.mark.parametrize("email, password", [
    ("", "Test@1234"),
    ("dev@test.com", ""),
    ("", ""),
], ids=["TC_LOGIN_07_empty_email", "TC_LOGIN_08_empty_password", "TC_LOGIN_09_both_empty"])
def test_login_empty_fields(driver, base_url, timeout, email, password):
    # The login form has `novalidate`, so the browser does NOT block empty fields:
    # the form is sent and the SERVER answers with an error message.
    page = LoginPage(driver, base_url, timeout).open()
    page.login(email, password)          # login() waits for the next page (dashboard or flash-error)
    assert page.error_message == "Please enter a valid email and password."
    assert page.current_path.startswith("/login")
    assert not page.is_logged_in


def test_TC_LOGIN_10_invalid_email_format(driver, base_url, timeout):
    page = LoginPage(driver, base_url, timeout).open()
    page.login("dev-at-test.com", "Test@1234")
    assert page.error_message == "Invalid email or password."
    assert not page.is_logged_in


def test_login_with_enter_key(driver, base_url, timeout):
    page = LoginPage(driver, base_url, timeout).open()
    page.type("login-email-input", "dev@test.com")
    page.find("login-password-input").send_keys("Test@1234", Keys.ENTER)   # press Enter instead of clicking
    page.wait_for("dashboard-heading")
    assert page.current_path == "/dashboard"


def test_logout(driver, base_url, timeout):
    dashboard = LoginPage(driver, base_url, timeout).login_as("dev@test.com")
    dashboard.logout()
    assert dashboard.exists("login-form")
    assert "You have been logged out." in dashboard.flash_messages("info")
