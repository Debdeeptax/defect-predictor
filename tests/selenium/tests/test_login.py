"""Sample Selenium test 1 — login with each seeded role, and a rejected login."""
import pytest

from tests.selenium.pages import LoginPage


@pytest.mark.parametrize("email,role", [
    ("dev@test.com", "developer"),
    ("qa@test.com", "qa"),
    ("admin@test.com", "admin"),
])
def test_login_success_shows_dashboard_with_role(driver, base_url, timeout, email, role):
    page = LoginPage(driver, base_url, timeout).open()
    page.login(email, "Test@1234")

    assert page.exists("dashboard-heading")
    assert page.current_path == "/dashboard"
    assert page.user_role == role
    assert any("Welcome back" in m for m in page.flash_messages("success"))


def test_login_with_wrong_password_shows_error(driver, base_url, timeout):
    page = LoginPage(driver, base_url, timeout).open()
    page.login("dev@test.com", "not-the-password1")

    assert not page.is_logged_in
    assert page.error_message == "Invalid email or password."
    assert page.exists("login-form")


def test_logout_returns_to_login(driver, base_url, timeout):
    dashboard = LoginPage(driver, base_url, timeout).login_as("qa@test.com")
    dashboard.logout()
    assert dashboard.exists("login-form") and not dashboard.is_logged_in
