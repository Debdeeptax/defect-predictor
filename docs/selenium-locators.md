# Selenium locators

Every interactive element (links, buttons, inputs, selects, table rows, alerts, nav items)
has a stable **`data-testid`** and a page-unique **`id`**, both kebab-case. Prefer
`data-testid`; it is the contract. Styling classes may change at any time.

```python
from selenium.webdriver.common.by import By
driver.find_element(By.CSS_SELECTOR, '[data-testid="login-email-input"]')
# or with the POM helper:  from tests.selenium.pages import tid;  driver.find_element(*tid("login-email-input"))
```

This file is checked by `tests/integration/test_locator_docs.py`: every `data-testid` in
`app/templates/` must be listed here (dynamic ids as patterns), so the doc can't drift.
The page audit `tests/integration/test_testids.py` enforces "testid + unique id" on every page.

## Conventions

| Placeholder | Meaning | Example |
|---|---|---|
| `<path-key>` | file path → lowercase, every run of non-alphanumerics → `-` (helper `path_key()` in `tests/selenium/pages/base_page.py`) | `legacy/report_builder.py` → `legacy-report-builder-py` |
| `<email-key>` | user email with the same rule | `dev@test.com` → `dev-test-com` |
| `<id>` | numeric database id (report, job, …) | `report-link-3` |
| `<level>` | model level: `function` or `class` | `active-badge-class` |
| `<n>` | model version number | `activate-btn-function-v2` |
| `<i>` | 1-based position in a list | `unit-row-inventory-pricing-py-2` |
| `<category>` | flash category: `success`, `error`, `warning`, `info` | `flash-error` |

**Sync markers (no sleeps needed).** Pages that finish work render a marker. Wait for its *presence*:

| Marker | Where |
|---|---|
| `status-done` | report page when the analysis finished; compare page when a comparison is shown; training-job page when training succeeded |
| `status-failed` | report page of a failed analysis; training-job page when training failed |
| `status-running` | report page while an analysis is still running (normally never seen: analysis is synchronous) |
| `loading-indicator` | overlay shown while a long form submission (upload / retrain) is in flight; on the job page, the running spinner (page auto-refreshes every 3 s) |

Charts are drawn without animation; `risk-chart` / `top-files-chart` get `data-rendered="true"` once drawn.

**Seed data** (`python scripts/reset_db.py`): `dev@test.com`, `qa@test.com`, `admin@test.com`
(password `Test@1234`) and report **#1** "Sample project (seed)" owned by dev.
Upload fixture: `data/samples/sample_project.zip` (8 files; riskiest `legacy/report_builder.py` = Medium).

## Global layout (every page)

| data-testid | Element | Notes |
|---|---|---|
| `page-<name>` | `<body>` | page name: `login`, `register`, `dashboard`, `upload`, `reports`, `report-detail`, `compare`, `admin-users`, `admin-models`, `admin-job`, `admin-logs`, `error-403`, `error-404`, `error-500`, `generic` |
| `main-nav` | top navbar | |
| `nav-brand` | logo link | → dashboard / login |
| `nav-toggle-btn` | burger button | narrow screens only |
| `nav-dashboard` | nav link | logged in |
| `nav-upload` | nav link | Developer, Admin |
| `nav-reports` | nav link | text "My reports" (Developer) / "All reports" (QA, Admin) |
| `nav-compare` | nav link | QA, Admin |
| `nav-admin-models` | nav link | Admin |
| `nav-admin-users` | nav link | Admin |
| `nav-admin-logs` | nav link | Admin |
| `nav-user-name` | current user's name | |
| `nav-user-role` | role badge | attribute `data-role` = `developer` / `qa` / `admin` |
| `logout-btn` | button (POST form) | |
| `nav-login` | link | logged out |
| `nav-register` | link | logged out |
| `main-content` | `<main>` | |
| `flash-container` | wrapper of flash messages | |
| `flash-<category>` | alert `<div>` | ids `flash-<category>-<i>`; text in `.flash-message` |
| `flash-close-btn` | alert close button | ids `flash-close-<i>` |
| `loading-indicator` | full-page loading overlay | `hidden` until a long form is submitted |

## /login

| data-testid | Element |
|---|---|
| `login-heading` | heading |
| `login-form` | form |
| `login-email-input` | email input |
| `login-password-input` | password input |
| `login-remember-checkbox` | "remember me" checkbox |
| `login-submit-btn` | submit button |
| `login-register-link` | link to /register |

Failure → stays on /login with `flash-error` "Invalid email or password." (or "…deactivated…").

## /register

| data-testid | Element |
|---|---|
| `register-heading` | heading |
| `register-form` | form |
| `register-name-input` | full name |
| `register-email-input` | email |
| `register-password-input` | password (≥ 8 chars, letters + digits) |
| `register-confirm-input` | confirm password |
| `register-submit-btn` | submit |
| `register-login-link` | link to /login |

Success → /login with `flash-success` "Account created…". New users are Developers.

## /dashboard

| data-testid | Element | Notes |
|---|---|---|
| `dashboard-heading` | heading | presence = logged-in landing page |
| `dashboard-scope` | "Your submissions" / "All users" | |
| `dashboard-analyze-btn` | link to /upload | Developer, Admin |
| `stat-<key>` | stat value | key: `reports`, `files`, `high`, `medium`, `low` |
| `recent-reports-table` | table | latest 5 visible reports |
| `recent-report-row-<id>` | table row | |
| `recent-report-link-<id>` | report link | |
| `dashboard-all-reports-link` | link to /reports | |
| `dashboard-empty` | empty-state text | no reports |
| `dashboard-empty-upload-link` | link to /upload | empty state |
| `model-status-card` | active-models card | |
| `model-status-<level>` | model line | |
| `model-missing-<level>` | "No active model" | when missing |

## /upload  (Developer, Admin)

| data-testid | Element | Notes |
|---|---|---|
| `upload-heading` | heading | |
| `upload-form` | form | `multipart/form-data`; shows `loading-indicator` on submit |
| `source-file-radio` | radio "File or ZIP" | visually a button; click via JS or its label |
| `source-git-radio` | radio "Git repository" | |
| `file-panel` | file input panel | hidden when Git is selected |
| `upload-file-input` | `<input type=file>` | `send_keys(absolute_path)`; source file or `.zip` |
| `git-panel` | Git URL panel | hidden when File is selected |
| `git-url-input` | URL input | public `https://github.com/owner/repo` etc. |
| `report-title-input` | optional report title | |
| `analyze-btn` | submit | success → `/reports/<id>` with `status-done`; error → `flash-error` on /upload |
| `supported-languages` | info text | |

## /reports  (list)

| data-testid | Element | Notes |
|---|---|---|
| `reports-heading` | heading | |
| `reports-filter-form` | filter form | |
| `risk-filter-select` | select: all / high / medium | auto-submits on change |
| `risk-filter-btn` | submit button | only rendered without JavaScript (`<noscript>`) |
| `reports-table` | table | client-side sortable (`data-sorted-by`) |
| `reports-sort-id` / `reports-sort-title` / `reports-sort-owner` / `reports-sort-created` / `reports-sort-files` / `reports-sort-high` / `reports-sort-medium` / `reports-sort-max` | sortable header buttons | `owner` only for QA/Admin |
| `report-list-row-<id>` | row | |
| `report-link-<id>` | link to report | |
| `report-status-<id>` | status badge | `done` / `failed` / `running` |
| `reports-empty` | empty state | |
| `reports-pagination` | pagination nav | > 20 reports |
| `reports-prev-page` / `reports-next-page` | pagination links | |
| `reports-page-info` | "Page x / y" | |

## /reports/&lt;id&gt;  (report detail)

| data-testid | Element | Notes |
|---|---|---|
| `report-id` | report number | |
| `report-title` | title | |
| `report-meta` | source / owner / date | |
| `status-done` / `status-failed` / `status-running` | status marker | see sync markers |
| `report-error` | error alert | failed analyses |
| `report-pending` | info alert | still running |
| `export-csv-btn` | file-level CSV download link | `/reports/<id>/export.csv` |
| `export-units-csv-btn` | unit-level CSV link | `/reports/<id>/export.csv?level=unit` |
| `export-pdf-btn` | PDF link | `/reports/<id>/export.pdf` |
| `summary-<key>` | summary value | key: `files`, `high`, `medium`, `low`, `max-prob`, `units` |
| `risk-chart` | doughnut `<canvas>` | `data-rendered="true"` when drawn |
| `top-files-chart` | bar `<canvas>` | `data-rendered="true"` when drawn |
| `report-warning` | warning alert(s) | e.g. partial metrics for non-Python files |
| `report-table` | ranked file table | default order: probability desc; `data-sorted-by="<key>:<ascending|descending>"` after a header click |
| `sort-rank` / `sort-file` / `sort-language` / `sort-risk` / `sort-probability` / `sort-loc` / `sort-max-cc` | sortable header buttons | first click: numbers ↓, text A→Z |
| `report-row-<path-key>` | file row | attribute `data-path` = original path |
| `file-path-<path-key>` | path text | |
| `risk-badge-<path-key>` | risk badge | text and `data-risk` = `High` / `Medium` / `Low` |
| `prob-<path-key>` | probability cell | `data-sort-value` = probability (float) |
| `units-row-<path-key>` | drill-down row under each file | |
| `units-<path-key>` | `<details>` element | |
| `units-toggle-<path-key>` | `<summary>`, click to expand | no animation |
| `units-table-<path-key>` | unit table | visible once expanded |
| `unit-row-<path-key>-<i>` | unit row | sorted by probability desc |
| `unit-risk-badge-<path-key>-<i>` | unit risk badge | `data-risk` |
| `models-used-card` | models card | |
| `skipped-card` | skipped files card | |
| `skipped-count` | number skipped | |
| `skipped-list` | list of skipped files + reasons | |

## /reports/compare  (QA, Admin)

| data-testid | Element | Notes |
|---|---|---|
| `compare-heading` | heading | |
| `compare-empty` | info | fewer than 2 completed reports |
| `compare-form` | GET form | |
| `compare-a-select` | baseline report select | option values = report ids |
| `compare-b-select` | compared report select | |
| `compare-submit-btn` | submit | → `status-done` + results |
| `compare-<key>` | summary value | key: `common`, `worse`, `better`, `added`, `removed`, `mean-delta` |
| `compare-table` | result table | sortable |
| `compare-sort-file` / `compare-sort-prob-a` / `compare-sort-prob-b` / `compare-sort-delta` | header buttons | |
| `compare-row-<path-key>` | row | |
| `compare-risk-a-<path-key>` / `compare-risk-b-<path-key>` | risk badges | `data-risk` |
| `compare-delta-<path-key>` | Δ probability | |
| `compare-change-<path-key>` | `same` / `worse` / `better` / `added` / `removed` | |

## /admin/users  (Admin)

| data-testid | Element | Notes |
|---|---|---|
| `users-heading` | heading | |
| `users-table` | table | |
| `user-row-<email-key>` | row | |
| `role-select-<email-key>` | role select | values `developer` / `qa` / `admin` |
| `role-save-btn-<email-key>` | save role | → `flash-success` / `flash-error` (own admin role can't be removed) |
| `user-status-<email-key>` | `active` / `inactive` badge | |
| `toggle-active-btn-<email-key>` | activate / deactivate | disabled for yourself |

## /admin/models  (Admin)

| data-testid | Element | Notes |
|---|---|---|
| `models-heading` | heading | |
| `model-card-<level>` | card per level | |
| `versions-table-<level>` | versions table | |
| `version-row-<level>-v<n>` | version row | |
| `active-badge-<level>` | "active" badge | attribute `data-version` = active version |
| `activate-btn-<level>-v<n>` | activate button | on non-active versions |
| `no-models-<level>` | empty state | |
| `training-running` | info alert | while a job is queued/running |
| `running-job-link` | link to the running job | |
| `retrain-form` | form | shows `loading-indicator` on submit |
| `retrain-level-select` | `function` / `class` | |
| `retrain-preset-select` | `quick` (3×1) / `standard` (5×5) | |
| `retrain-csv-input` | optional training CSV | |
| `retrain-activate-checkbox` | activate when done (checked by default) | |
| `retrain-submit-btn` | start | → `/admin/models/jobs/<id>` |
| `jobs-table` | recent jobs | |
| `jobs-empty` | empty state | |
| `job-row-<id>` / `job-link-<id>` / `job-status-<id>` | job row / link / status badge | |

## /admin/models/jobs/&lt;id&gt;  (Admin)

| data-testid | Element | Notes |
|---|---|---|
| `job-heading` | heading | |
| `back-to-models-btn` | link | |
| `job-status` | status badge | `data-status` = `queued` / `running` / `done` / `failed` |
| `status-done` / `status-failed` | finished markers | page auto-refreshes every 3 s until one appears. Wait with a long timeout (standard CV can take ~15 min) |
| `loading-indicator` | running spinner | |
| `job-error` | error alert | failed jobs |
| `job-result` | success summary | |
| `job-summary-table` | candidate comparison | |
| `job-log` | progress log `<pre>` | |

## /admin/logs  (Admin)

| data-testid | Element | Notes |
|---|---|---|
| `logs-heading` | heading | |
| `audit-filter-form` | filter form | |
| `audit-action-select` | action filter | auto-submits; e.g. `login`, `analysis`, `export_pdf`, `role_change`, `retrain_start` |
| `audit-filter-btn` | submit | `<noscript>` only |
| `audit-table` | audit events | |
| `audit-row` | event row (shared testid, use `find_elements`) | ids `audit-row-<id>`; attribute `data-action` |
| `audit-empty` | empty-state row | |
| `app-log` | tail of `logs/app.log` | |

## Error pages (403 / 404 / 500)

| data-testid | Element |
|---|---|
| `error-code` | `403` / `404` / `500` |
| `error-title` | title |
| `error-message` | explanation |
| `error-home-btn` | link to dashboard |

## Page Object Model

`tests/selenium/pages/`: `BasePage` (waits, `find`/`click`/`type` by testid, flashes, nav, role, logout),
`LoginPage`, `UploadPage`, `ReportPage`. Samples: `tests/selenium/tests/` (login, upload + predict,
role access). See the README for how to run them.
