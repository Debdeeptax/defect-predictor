from __future__ import annotations

from tests.selenium.pages.base_page import BasePage, path_key


class ReportPage(BasePage):
    """/reports/<id> — summary, charts, ranked file table, exports."""
    PAGE_TESTID = "report-title"

    def open_report(self, report_id: int) -> "ReportPage":
        self.open(f"/reports/{report_id}")
        return self

    # ------------------------------------------------------------------ state
    def wait_until_done(self) -> "ReportPage":
        self.wait_for("status-done")
        return self

    @property
    def is_done(self) -> bool:
        return self.exists("status-done")

    @property
    def is_failed(self) -> bool:
        return self.exists("status-failed")

    @property
    def report_id(self) -> int:
        return int(self.text("report-id"))

    @property
    def title(self) -> str:
        return self.text("report-title")

    def summary(self) -> dict[str, str]:
        """Values of the summary cards: files, high, medium, low, max-prob, units."""
        return {k: self.text(f"summary-{k}") for k in ("files", "high", "medium", "low", "max-prob", "units")}

    def charts_rendered(self) -> bool:
        return all(self.find(t).get_attribute("data-rendered") == "true"
                   for t in ("risk-chart", "top-files-chart"))

    # ------------------------------------------------------------------ file table
    def file_paths(self) -> list[str]:
        """File paths in current table order."""
        rows = self.driver.find_elements("css selector", '[data-testid="report-table"] tbody tr[data-row]')
        return [r.get_attribute("data-path") for r in rows]

    def risk_of(self, path: str) -> str:
        return self.find(f"risk-badge-{path_key(path)}").get_attribute("data-risk")

    def probability_of(self, path: str) -> float:
        cell = self.find(f"prob-{path_key(path)}")
        return float(cell.get_attribute("data-sort-value"))

    def sort_by(self, column: str) -> str:
        """column: rank | file | language | risk | probability | loc | max-cc.
        Returns the table's data-sorted-by value, e.g. 'file:ascending'."""
        self.click(f"sort-{column}")
        return self.find("report-table").get_attribute("data-sorted-by")

    def expand_units(self, path: str) -> list[str]:
        """Open a file's unit drill-down; returns the unit risk labels."""
        key = path_key(path)
        self.click(f"units-toggle-{key}")
        self.wait_visible(f"units-table-{key}")
        return [b.get_attribute("data-risk") for b in self.driver.find_elements(
            "css selector", f'[data-testid="units-table-{key}"] .risk-badge')]

    # ------------------------------------------------------------------ exports
    def export_url(self, kind: str = "pdf") -> str:
        """kind: pdf | csv | units-csv. Returns the download link (fetch it with requests
        or check the href; headless Chrome downloads are not inspected here)."""
        testid = {"pdf": "export-pdf-btn", "csv": "export-csv-btn", "units-csv": "export-units-csv-btn"}[kind]
        return self.find(testid).get_attribute("href")
