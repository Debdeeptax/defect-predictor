"""Sample Selenium test 3 — role-based access: navigation per role and direct-URL blocking."""
import pytest

from tests.selenium.pages import LoginPage

NAV = {
    "dev@test.com": {"nav-dashboard", "nav-upload", "nav-reports"},
    "qa@test.com": {"nav-dashboard", "nav-reports", "nav-compare"},
    "admin@test.com": {"nav-dashboard", "nav-upload", "nav-reports", "nav-compare",
                       "nav-admin-models", "nav-admin-users", "nav-admin-logs"},
}


@pytest.mark.parametrize("email", NAV)
def test_navigation_matches_role(driver, base_url, timeout, email):
    page = LoginPage(driver, base_url, timeout).login_as(email)
    links = page.nav_items() - {"nav-brand", "nav-toggle-btn", "nav-user-name", "nav-user-role"}
    assert links == NAV[email]


@pytest.mark.parametrize("email,path,expected", [
    ("dev@test.com", "/admin/models", "403"),
    ("dev@test.com", "/reports/compare", "403"),
    ("qa@test.com", "/upload", "403"),
    ("qa@test.com", "/admin/users", "403"),
    ("admin@test.com", "/admin/users", None),
])
def test_direct_url_access_is_enforced(driver, base_url, timeout, email, path, expected):
    page = LoginPage(driver, base_url, timeout).login_as(email)
    page.open(path)
    assert page.error_code == expected


def test_anonymous_user_is_sent_to_login(driver, base_url, timeout):
    page = LoginPage(driver, base_url, timeout)
    page.open("/reports")
    assert page.current_path.startswith("/login")
    assert page.exists("login-form")
