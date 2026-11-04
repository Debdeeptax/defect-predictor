"""Selenium fixtures.

By default an isolated, freshly seeded app is served in a background thread on a free
port, so every run starts from the same known state (seed users + sample report).

Environment variables
---------------------
SDP_BASE_URL   test an already running server instead (e.g. http://127.0.0.1:5000).
               Reset it first with `python scripts/reset_db.py` for repeatable results.
SDP_HEADLESS   "0" to watch the browser (default: headless).
SDP_TIMEOUT    explicit-wait timeout in seconds (default 30).
"""
from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path

import pytest

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"


def pytest_collection_modifyitems(items):
    for item in items:
        if "tests/selenium" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.selenium)


@pytest.fixture(scope="session")
def base_url(tmp_path_factory):
    external = os.getenv("SDP_BASE_URL")
    if external:
        yield external.rstrip("/")
        return

    from werkzeug.serving import make_server

    from tests.helpers import build_test_app

    app = build_test_app(tmp_path_factory.mktemp("selenium-app"), csrf=True)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="sdp-live-server")
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture(scope="session")
def _browser():
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException

    opts = webdriver.ChromeOptions()
    if os.getenv("SDP_HEADLESS", "1") != "0":
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1400,1000")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    # Chrome's password manager (save-password / "password found in a data breach" bubbles,
    # partly switched on remotely via field trials) steals keyboard focus after the first
    # login, so later password typing and clicks silently go nowhere. Turn it all off.
    opts.add_experimental_option("prefs", {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
        "profile.password_manager_leak_detection": False,
        "autofill.profile_enabled": False,
    })
    opts.add_argument("--disable-features=PasswordLeakDetection,PasswordManagerOnboarding,"
                      "AutofillServerCommunication,PasswordCheck")
    opts.add_argument("--password-store=basic")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-sync")
    opts.set_capability("goog:loggingPrefs", {"browser": "ALL"})
    try:
        drv = webdriver.Chrome(options=opts)  # Selenium Manager resolves chromedriver
    except WebDriverException as exc:
        pytest.skip(f"Chrome / chromedriver not available: {exc.msg}")
    yield drv
    drv.quit()


@pytest.fixture
def driver(_browser, base_url):
    """Fresh session per test: cookies cleared, starts on the login page."""
    _browser.delete_all_cookies()
    _browser.get(base_url + "/login")
    _browser.delete_all_cookies()
    yield _browser


@pytest.fixture
def timeout() -> int:
    return int(os.getenv("SDP_TIMEOUT", "30"))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Save a screenshot + page source when a Selenium test fails."""
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call" and rep.failed and "driver" in item.fixturenames:
        drv = item.funcargs.get("driver")
        if drv is not None:
            ARTIFACTS.mkdir(exist_ok=True)
            stem = f"{datetime.now():%Y%m%d-%H%M%S}-{item.name}".replace("/", "_")[:120]
            try:
                drv.save_screenshot(str(ARTIFACTS / f"{stem}.png"))
                (ARTIFACTS / f"{stem}.html").write_text(drv.page_source, encoding="utf-8")
            except Exception:
                pass
