"""Page Object Model base. All locators use `data-testid` (see docs/selenium-locators.md)."""
from __future__ import annotations

import re

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


def tid(testid: str) -> tuple[str, str]:
    """Locator for an element by its data-testid."""
    return By.CSS_SELECTOR, f'[data-testid="{testid}"]'


def path_key(path: str) -> str:
    """The key used in per-file test ids (mirrors the `testid` Jinja filter):
    'legacy/report_builder.py' -> 'legacy-report-builder-py'."""
    return re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-") or "x"


class BasePage:
    PATH = "/"
    PAGE_TESTID: str | None = None  # data-testid on <body> (page-<name>) once loaded

    def __init__(self, driver: WebDriver, base_url: str, timeout: int = 30):
        self.driver = driver
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.wait = WebDriverWait(driver, timeout)

    # ------------------------------------------------------------------ navigation
    def open(self, path: str | None = None) -> "BasePage":
        self.driver.get(self.base_url + (path if path is not None else self.PATH))
        return self.wait_loaded()

    def wait_loaded(self) -> "BasePage":
        if self.PAGE_TESTID:
            self.wait_for(self.PAGE_TESTID)
        return self

    @property
    def current_path(self) -> str:
        url = self.driver.current_url
        return url[len(self.base_url):] if url.startswith(self.base_url) else url

    # ------------------------------------------------------------------ element helpers
    def find(self, testid: str) -> WebElement:
        return self.driver.find_element(*tid(testid))

    def find_all(self, testid: str) -> list[WebElement]:
        return self.driver.find_elements(*tid(testid))

    def exists(self, testid: str) -> bool:
        return bool(self.find_all(testid))

    def wait_for(self, testid: str, timeout: int | None = None) -> WebElement:
        wait = WebDriverWait(self.driver, timeout) if timeout else self.wait
        return wait.until(EC.presence_of_element_located(tid(testid)))

    def wait_visible(self, testid: str) -> WebElement:
        return self.wait.until(EC.visibility_of_element_located(tid(testid)))

    def click(self, testid: str) -> None:
        self.wait.until(EC.element_to_be_clickable(tid(testid))).click()

    def type(self, testid: str, text: str, clear: bool = True) -> None:
        el = self.wait_visible(testid)
        if clear:
            el.clear()
        el.send_keys(text)

    def text(self, testid: str) -> str:
        return self.find(testid).text.strip()

    # ------------------------------------------------------------------ shared layout
    def flash_messages(self, category: str = "error") -> list[str]:
        """category: success | error | warning | info"""
        return [e.text.replace("×", "").strip() for e in self.find_all(f"flash-{category}")]

    def wait_for_flash(self, category: str = "error") -> str:
        return self.wait_for(f"flash-{category}").text.strip()

    @property
    def is_logged_in(self) -> bool:
        return self.exists("logout-btn")

    @property
    def user_role(self) -> str | None:
        """'developer' | 'qa' | 'admin' (from the nav badge), or None when logged out."""
        els = self.find_all("nav-user-role")
        return els[0].get_attribute("data-role") if els else None

    def nav_items(self) -> set[str]:
        """data-testids of the visible top-navigation links (e.g. {'nav-dashboard', ...})."""
        links = self.driver.find_elements(By.CSS_SELECTOR, '#main-nav [data-testid^="nav-"]')
        return {e.get_attribute("data-testid") for e in links}

    def logout(self) -> None:
        self.click("logout-btn")
        self.wait_for("login-heading")

    @property
    def error_code(self) -> str | None:
        """403 / 404 / 500 when the generic error page is shown."""
        els = self.find_all("error-code")
        return els[0].text.strip() if els else None
