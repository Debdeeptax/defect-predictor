from __future__ import annotations

from tests.selenium.pages.base_page import BasePage


class LoginPage(BasePage):
    PATH = "/login"
    PAGE_TESTID = "login-form"

    def login(self, email: str, password: str) -> None:
        """Submit credentials. Returns after the next page has loaded (dashboard on success,
        login page with `flash-error` on failure)."""
        self.type("login-email-input", email)
        self.type("login-password-input", password)
        old = self.find("login-form")
        self.click("login-submit-btn")
        self.wait.until(lambda d: _is_stale(old))
        self.wait.until(lambda d: self.exists("dashboard-heading") or self.exists("flash-error"))

    def login_as(self, email: str, password: str = "Test@1234"):
        """Log in and return the dashboard as a BasePage (fails if login is rejected)."""
        self.open()
        self.login(email, password)
        assert self.exists("dashboard-heading"), f"login failed: {self.flash_messages()}"
        return BasePage(self.driver, self.base_url, self.timeout)

    @property
    def error_message(self) -> str:
        msgs = self.flash_messages("error")
        return msgs[0] if msgs else ""

    def go_to_register(self) -> None:
        self.click("login-register-link")
        self.wait_for("register-form")


def _is_stale(element) -> bool:
    try:
        element.is_enabled()
        return False
    except Exception:
        return True
