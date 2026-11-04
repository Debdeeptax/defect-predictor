# Software Defect Prediction System

Web app that extracts static code metrics from submitted source code (file, ZIP or Git URL), runs trained ML models, and reports defect-proneness per file.

> Work in progress — see [docs/PLAN.md](docs/PLAN.md) for the design and phase plan. Full setup/run instructions arrive in Phase 7.

## Quick setup (dev)

```powershell
& "C:\Program Files\Python311\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
```

## Selenium tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests/selenium -v          # headless Chrome, isolated seeded app on a free port
$env:SDP_HEADLESS="0"; .\.venv\Scripts\python.exe -m pytest tests/selenium   # watch the browser
# against a running server (reset it first for repeatable data):
.\.venv\Scripts\python.exe scripts/reset_db.py; $env:SDP_BASE_URL="http://127.0.0.1:5000"; .\.venv\Scripts\python.exe -m pytest tests/selenium
```

- Locators: [docs/selenium-locators.md](docs/selenium-locators.md) (`data-testid` on every interactive element).
- Page Objects: `tests/selenium/pages/` (`BasePage`, `LoginPage`, `UploadPage`, `ReportPage`).
- Seed users: `dev@test.com`, `qa@test.com`, `admin@test.com` / `Test@1234`; upload fixture `data/samples/sample_project.zip`.
- Failing Selenium tests save a screenshot + HTML to `tests/selenium/artifacts/`.
- Skip browser tests: `pytest -m "not selenium"`.
