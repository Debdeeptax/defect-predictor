from __future__ import annotations

from pathlib import Path

from tests.selenium.pages.base_page import BasePage
from tests.selenium.pages.report_page import ReportPage

ANALYSIS_TIMEOUT = 180  # large repositories / git clones can take a while


class UploadPage(BasePage):
    PATH = "/upload"
    PAGE_TESTID = "upload-form"

    def choose_file_source(self) -> None:
        self.driver.execute_script("arguments[0].click()", self.find("source-file-radio"))

    def choose_git_source(self) -> None:
        self.driver.execute_script("arguments[0].click()", self.find("source-git-radio"))
        self.wait_visible("git-url-input")

    def set_title(self, title: str) -> None:
        self.type("report-title-input", title)

    def select_file(self, path: str | Path) -> None:
        # File inputs accept an absolute path via send_keys (no OS dialog).
        self.find("upload-file-input").send_keys(str(Path(path).resolve()))

    def submit(self) -> None:
        self.click("analyze-btn")

    def upload_file(self, path: str | Path, title: str | None = None) -> ReportPage:
        """Upload a source file or .zip and wait for the finished report."""
        self.choose_file_source()
        self.select_file(path)
        if title:
            self.set_title(title)
        self.submit()
        return self._wait_for_result()

    def analyse_git(self, url: str, title: str | None = None) -> ReportPage:
        self.choose_git_source()
        self.type("git-url-input", url)
        if title:
            self.set_title(title)
        self.submit()
        return self._wait_for_result()

    def submit_expecting_error(self) -> str:
        """Submit and return the error flash text (form stays on /upload)."""
        self.submit()
        return self.wait_for_flash("error")

    def _wait_for_result(self) -> ReportPage:
        # The loading overlay is shown while the server works; the report page carries
        # `status-done` once results are rendered. An error re-renders this page with a flash.
        self.wait_for_any(("status-done", "status-failed", "flash-error"), ANALYSIS_TIMEOUT)
        return ReportPage(self.driver, self.base_url, self.timeout)

    def wait_for_any(self, testids, timeout: int) -> None:
        from selenium.webdriver.support.ui import WebDriverWait
        WebDriverWait(self.driver, timeout).until(
            lambda d: any(self.exists(t) for t in testids))
