r"""
YOUR FIRST SELENIUM SCRIPT (no pytest, no page objects) for the Defect Prediction System.

Before running: start the app in another PowerShell window with  .\.venv\Scripts\python.exe run.py
Run:            .\.venv\Scripts\python.exe tests\selenium\selenium_first_script.py

It does the 4 things every automated test does:
  1. OPEN a page   2. PERFORM actions   3. VERIFY the result   4. RECORD the result
"""
import os
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

APP_URL = os.getenv("SDP_BASE_URL", "http://127.0.0.1:5000")

options = webdriver.ChromeOptions()
# Stop Chrome's "save password?" pop-up from stealing keyboard focus after logging in
options.add_experimental_option("prefs", {
    "credentials_enable_service": False,
    "profile.password_manager_enabled": False,
    "profile.password_manager_leak_detection": False,
})
if os.getenv("SDP_HEADLESS") == "1":
    options.add_argument("--headless=new")

driver = webdriver.Chrome(options=options)     # opens Chrome (chromedriver is downloaded automatically)
wait = WebDriverWait(driver, 15)               # explicit wait: up to 15 seconds

try:
    # 1. OPEN the login page
    driver.get(APP_URL + "/login")
    print("Opened:", driver.title)

    # 2. PERFORM ACTIONS - find each element by its data-testid and use it
    driver.find_element(By.CSS_SELECTOR, '[data-testid="login-email-input"]').send_keys("dev@test.com")
    driver.find_element(By.CSS_SELECTOR, '[data-testid="login-password-input"]').send_keys("Test@1234")
    driver.find_element(By.CSS_SELECTOR, '[data-testid="login-submit-btn"]').click()

    # 3. VERIFY - wait for the dashboard heading, then check the URL and the role badge
    heading = wait.until(EC.visibility_of_element_located(
        (By.CSS_SELECTOR, '[data-testid="dashboard-heading"]')))
    role = driver.find_element(By.CSS_SELECTOR, '[data-testid="nav-user-role"]').get_attribute("data-role")
    assert driver.current_url.endswith("/dashboard"), driver.current_url
    assert role == "developer", role

    # 4. RECORD
    Path("reports").mkdir(exist_ok=True)
    driver.save_screenshot("reports/first_script_PASS.png")
    print("Heading:", heading.text, "| role:", role)
    print("RESULT: PASS - screenshot saved to reports\\first_script_PASS.png")
except Exception as error:
    Path("reports").mkdir(exist_ok=True)
    driver.save_screenshot("reports/first_script_FAIL.png")
    print("RESULT: FAIL -", error)
    raise
finally:
    driver.quit()                              # always close the browser
