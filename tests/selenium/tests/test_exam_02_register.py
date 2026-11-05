"""EXAM SCENARIO 2 - REGISTRATION + FORM VALIDATION."""
import uuid

import pytest

from tests.selenium.pages import BasePage, LoginPage

WEAK = "Password must be at least 8 characters and contain letters and digits."


def unique_email():
    """A new address every run, so 'valid registration' never collides with an old account."""
    return f"student_{uuid.uuid4().hex[:8]}@test.com"


def fill_register_form(page, name, email, password, confirm):
    page.type("register-name-input", name)
    page.type("register-email-input", email)
    page.type("register-password-input", password)
    page.type("register-confirm-input", confirm)
    page.click("register-submit-btn")


@pytest.fixture
def register_page(driver, base_url, timeout):
    page = BasePage(driver, base_url, timeout)
    page.open("/register")
    page.wait_for("register-form")
    return page


def test_TC_REG_01_valid_registration_then_login(register_page, driver, base_url, timeout):
    email = unique_email()
    fill_register_form(register_page, "Asha Kumar", email, "Passw0rd1", "Passw0rd1")

    register_page.wait_for("login-form")                     # redirected to /login
    assert "Account created. You can log in now." in register_page.flash_messages("success")

    login = LoginPage(driver, base_url, timeout)
    login.login(email, "Passw0rd1")                           # the new account works
    assert login.current_path == "/dashboard"
    assert login.user_role == "developer"                     # new users are Developers


@pytest.mark.parametrize("name, email, password, confirm, expected", [
    ("Asha", "dev@test.com", "Passw0rd1", "Passw0rd1", "An account with this email already exists."),
    ("Asha", "NEW", "Passw0rd1", "Passw0rd2", "Passwords must match."),
    ("Asha", "NEW", "abc12", "abc12", "Field must be between 8 and 128 characters long."),
    ("Asha", "NEW", "password", "password", WEAK),
    ("Asha", "NEW", "12345678", "12345678", WEAK),
    ("Asha", "asha-at-test.com", "Passw0rd1", "Passw0rd1", "Please enter a valid email address."),
], ids=["TC_REG_02_duplicate_email", "TC_REG_03_password_mismatch", "TC_REG_04_password_too_short",
        "TC_REG_05_password_letters_only", "TC_REG_06_password_digits_only", "TC_REG_07_invalid_email"])
def test_registration_server_validation(register_page, name, email, password, confirm, expected):
    if email == "NEW":
        email = unique_email()
    fill_register_form(register_page, name, email, password, confirm)
    register_page.wait_for("flash-error")
    assert expected in register_page.flash_messages("error")
    assert register_page.exists("register-form")              # still on the register page


@pytest.mark.parametrize("field", ["register-name-input", "register-email-input",
                                   "register-password-input", "register-confirm-input"],
                         ids=["TC_REG_08_empty_name", "TC_REG_09_empty_email",
                              "TC_REG_10_empty_password", "TC_REG_11_empty_confirm"])
def test_registration_empty_field(register_page, field):
    values = {"register-name-input": "Asha", "register-email-input": unique_email(),
              "register-password-input": "Passw0rd1", "register-confirm-input": "Passw0rd1"}
    values[field] = ""                                        # leave ONE field empty
    for testid, value in values.items():
        if value:
            register_page.type(testid, value)
    register_page.click("register-submit-btn")
    # The form has `novalidate`: the server checks it and shows one flash per problem.
    register_page.wait_for("flash-error")
    assert "This field is required." in register_page.flash_messages("error")
    assert register_page.exists("register-form")
