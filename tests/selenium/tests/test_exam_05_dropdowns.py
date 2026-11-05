"""EXAM SCENARIO 5 - DROPDOWNS (<select>): report filter, compare two reports,
and an admin changing a user's role."""
from selenium.webdriver.support.ui import Select

from tests.selenium.pages import LoginPage, UploadPage, path_key
from tests.selenium.tests.test_exam_03_upload import SAMPLE_ZIP


def test_TC_DD_01_reports_risk_filter(driver, base_url, timeout):
    page = LoginPage(driver, base_url, timeout).login_as("dev@test.com")
    page.open("/reports")
    dropdown = Select(page.find("risk-filter-select"))
    assert [o.text for o in dropdown.options] == [
        "All reports", "With high-risk files", "With medium-risk files"]

    dropdown.select_by_value("medium")               # the page reloads by itself (auto-submit)
    page.wait.until(lambda d: "risk=medium" in d.current_url)
    assert page.exists("report-list-row-1")          # the seed report has 1 medium-risk file
    assert Select(page.find("risk-filter-select")).first_selected_option.text == "With medium-risk files"

    Select(page.find("risk-filter-select")).select_by_visible_text("With high-risk files")
    page.wait.until(lambda d: "risk=high" in d.current_url)
    assert not page.exists("report-list-row-1")      # it has 0 high-risk files


def test_TC_DD_02_qa_compares_two_reports(driver, base_url, timeout):
    # Precondition: two completed reports. The developer uploads a second one.
    LoginPage(driver, base_url, timeout).login_as("dev@test.com")
    second = UploadPage(driver, base_url, timeout).open().upload_file(SAMPLE_ZIP, title="For comparison")
    new_id = second.report_id
    second.logout()

    page = LoginPage(driver, base_url, timeout).login_as("qa@test.com")
    page.open("/reports/compare")
    Select(page.find("compare-a-select")).select_by_value("1")
    Select(page.find("compare-b-select")).select_by_value(str(new_id))
    page.click("compare-submit-btn")
    page.wait_for("status-done")
    assert page.text("compare-common") == "8"        # same project -> all 8 files in common
    assert page.text("compare-added") == "0"
    assert page.text("compare-removed") == "0"


def test_TC_DD_03_compare_same_report_twice_is_rejected(driver, base_url, timeout):
    page = LoginPage(driver, base_url, timeout).login_as("qa@test.com")
    page.open("/reports/compare?a=1&b=1")
    assert "Please choose two different reports." in page.flash_messages("error")


def test_TC_DD_04_admin_changes_role_with_dropdown(driver, base_url, timeout, new_user):
    # Precondition: a fresh user (so the seeded demo accounts stay unchanged).
    admin = LoginPage(driver, base_url, timeout).login_as("admin@test.com")   # returns a BasePage
    admin.open("/admin/users")
    admin.wait_for("users-table")
    key = path_key(new_user)                      # "user_ab12@test.com" -> "user-ab12-test-com"
    Select(admin.find(f"role-select-{key}")).select_by_value("qa")
    admin.click(f"role-save-btn-{key}")
    admin.wait_for("flash-success")
    assert Select(admin.find(f"role-select-{key}")).first_selected_option.get_attribute("value") == "qa"

    admin.logout()                                # the user now logs in with the QA role
    user = LoginPage(driver, base_url, timeout).login_as(new_user, "Passw0rd1")
    assert user.user_role == "qa"


def test_TC_DD_05_admin_deactivates_user_who_then_cannot_log_in(driver, base_url, timeout, new_user):
    admin = LoginPage(driver, base_url, timeout).login_as("admin@test.com")
    admin.open("/admin/users")
    key = path_key(new_user)
    admin.click(f"toggle-active-btn-{key}")
    admin.wait_for("flash-success")
    assert admin.text(f"user-status-{key}") == "inactive"
    admin.logout()

    login = LoginPage(driver, base_url, timeout).open()
    login.login(new_user, "Passw0rd1")
    assert login.error_message == "This account has been deactivated. Contact an administrator."
