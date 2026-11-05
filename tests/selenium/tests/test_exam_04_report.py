"""EXAM SCENARIO 4 - REPORT PAGE: verify results, sort a table, dynamic drill-down,
export links, and open the report in a NEW TAB (window handling)."""
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from tests.selenium.pages import LoginPage, ReportPage


def open_seed_report(driver, base_url, timeout):
    LoginPage(driver, base_url, timeout).login_as("dev@test.com")
    return ReportPage(driver, base_url, timeout).open_report(1)       # report #1 is created by the seed


def test_TC_REP_01_summary_matches_table(driver, base_url, timeout):
    report = open_seed_report(driver, base_url, timeout)
    assert report.title == "Sample project (seed)"
    assert report.is_done
    summary = report.summary()
    paths = report.file_paths()
    assert int(summary["files"]) == len(paths) == 8
    risks = [report.risk_of(p) for p in paths]
    assert risks.count("Medium") == int(summary["medium"])
    assert risks.count("High") == int(summary["high"])
    assert risks.count("Low") == int(summary["low"])
    assert report.charts_rendered()


def test_TC_REP_02_default_order_is_probability_descending(driver, base_url, timeout):
    report = open_seed_report(driver, base_url, timeout)
    probs = [report.probability_of(p) for p in report.file_paths()]
    assert probs == sorted(probs, reverse=True)
    assert all(0.0 <= p <= 1.0 for p in probs)


def test_TC_REP_03_sort_by_file_name(driver, base_url, timeout):
    report = open_seed_report(driver, base_url, timeout)
    before = report.file_paths()
    assert report.sort_by("file") == "file:ascending"
    assert report.file_paths() == sorted(before)
    assert report.sort_by("file") == "file:descending"               # second click reverses
    assert report.file_paths() == sorted(before, reverse=True)


def test_TC_REP_04_unit_drill_down(driver, base_url, timeout):
    report = open_seed_report(driver, base_url, timeout)
    table = "units-table-inventory-pricing-py"
    assert not report.find(table).is_displayed()                     # hidden before the click
    assert report.expand_units("inventory/pricing.py") == ["Low", "Low"]
    assert report.find(table).is_displayed()


def test_TC_REP_05_export_links(driver, base_url, timeout):
    report = open_seed_report(driver, base_url, timeout)
    assert report.export_url("pdf").endswith("/reports/1/export.pdf")
    assert report.export_url("csv").endswith("/reports/1/export.csv")
    assert report.export_url("units-csv").endswith("/reports/1/export.csv?level=unit")


def test_TC_REP_06_open_report_in_new_tab(driver, base_url, timeout):
    LoginPage(driver, base_url, timeout).login_as("dev@test.com")
    original = driver.current_window_handle

    driver.switch_to.new_window("tab")                               # open + switch to a new tab
    driver.get(base_url + "/reports/1")
    report = ReportPage(driver, base_url, timeout).wait_loaded()
    assert len(driver.window_handles) == 2
    assert report.title == "Sample project (seed)"

    driver.close()                                                   # close the new tab
    driver.switch_to.window(original)                                # back to the first tab
    assert driver.find_element(By.CSS_SELECTOR, '[data-testid="dashboard-heading"]')


def test_TC_REP_07_report_of_another_user_is_forbidden(driver, base_url, timeout, new_user):
    """A Developer may only see their OWN reports. Report #1 belongs to dev@test.com,
    so a different (newly registered) Developer must be refused."""
    page = LoginPage(driver, base_url, timeout).login_as(new_user, "Passw0rd1")
    page.open("/reports/1")
    assert page.error_code in ("403", "404")
