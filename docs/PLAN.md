# Software Defect Prediction System — Project Plan

## 1. Decisions (Phase 1, all defaults accepted)

| # | Topic | Decision |
|---|-------|----------|
| 1 | Location | `C:\Users\Admin\defect-predictor`, own git repo |
| 2 | Python | 3.11 in `.venv` |
| 3 | Languages | **Python: full metrics.** Java / C / C++ / C# / JS / TS / Go: partial (lizard CC, LOC, token-based Halstead approximation). Anything else → "unsupported language" warning, file skipped. |
| 4 | OO metrics | Python only, computed from `ast` (WMC, DIT, NOC, CBO, RFC, LCOM). Non-Python → OO columns `N/A`; no Java/CK tool dependency. |
| 5 | Datasets | **Two models.** Function-level on NASA MDP (McCabe + Halstead); class-level on PROMISE CK-metrics (OO). |
| 6 | Data source | Downloaded once in Phase 2, vendored in `data/raw/` with `SOURCES.md` (URL, licence, checksum). |
| 7 | Imbalance | Compare SMOTE (inside CV folds via `imblearn.Pipeline`) vs `class_weight="balanced"`. |
| 8 | Explainability | SHAP (TreeExplainer) for tree models; permutation importance fallback. |
| 9 | Risk labels | Low < 0.4 ≤ Medium < 0.7 ≤ High (configurable in `.env`). |
| 10 | Git URLs | Public HTTPS only, host allow-list, shallow clone (`depth=1`), timeout. |
| 11 | Limits | 20 MB upload, 2 000 files/analysis, ignore `venv`, `.venv`, `node_modules`, `.git`, `build`, `dist`, `__pycache__`, `site-packages`. |
| 12 | Execution | Synchronous; result page always carries `data-testid="status-done"`; loading overlay on submit. |
| 13 | Registration | Open; self-registered users are **Developer**; Admin promotes to QA/Admin. |
| 14 | Seed users | `dev@test.com`, `qa@test.com`, `admin@test.com` — password `Test@1234`. |
| 15 | Compare runs | QA selects two reports → per-file probability delta, new/removed files, risk-label changes. |
| 16 | PDF | ReportLab (pure Python). |
| 17 | UI | Bootstrap 5, vendored in `app/static/vendor/` (no CDN at runtime). |
| 18 | Charts | Chart.js, vendored. |
| 19 | Retrain | Built-in dataset or uploaded CSV (schema-validated). |
| 20 | Versioning | `models/{level}_v{N}_{algo}_{YYYYmmddHHMMSS}.joblib` + `model_versions` table (metrics JSON, feature list, active flag). |
| 21 | Logs | Rotating file log + `audit_events` table; Admin log viewer (tail N lines + audit list). |
| 22 | Deploy | Local `python run.py`; optional Dockerfile in Phase 7. |
| 23 | Selenium | Selenium Manager auto-driver; headless Chrome; fixture spins up app on test port with fresh seeded DB. |
| 24 | Git | Local commits only, one per phase. |
| 25 | Rigor | Paper-grade: repeated stratified 10×(5-fold) CV, mean ± std, Wilcoxon/Friedman test between models. |

## 2. ML design

### 2.1 Feature alignment (the critical constraint)
A model is only useful if the extractor can produce the same features at inference time. Training features are therefore **restricted to what we can extract**.

**Function-level model (NASA MDP — e.g. CM1, JM1, KC1, PC1, ...)**

| NASA column | Our extractor (Python via radon / others via lizard) |
|---|---|
| `loc`, `lOCode`, `lOComment`, `lOBlank` | radon raw / lizard nloc |
| `v(g)` cyclomatic | radon `cc` / lizard `CCN` |
| `n`, `v`, `l`, `d`, `i`, `e`, `b`, `t` | radon Halstead / token approximation |
| `uniq_Op`, `uniq_Opnd`, `total_Op`, `total_Opnd` | radon Halstead / token approximation |
| `branchCount` | derived (≈ 2·(v(g)−1)) |
| `ev(g)`, `iv(g)` | **Dropped** — not reliably extractable |

**Class-level model (PROMISE CK — e.g. ant, camel, jedit, log4j, lucene, xalan, ...)**
Features: `wmc, dit, noc, cbo, rfc, lcom, loc, max_cc, avg_cc, ce, npm, amc, lcom3` (others such as `ca, dam, moa, mfa, cam, ic, cbm` dropped as not extractable).

### 2.1b Data-cleaning decisions (Phase 2, user-approved 2026-11-04)
- **NASA PC2 skipped**: D'' PC2 lacks `LOC_BLANK`; skipping it keeps the feature for the other 11 projects.
- **Conflicting-label duplicates removed (both levels)**: identical metric vectors with contradictory labels are dropped entirely (same principle as Shepperd's D'' "inconsistent instances"). In PROMISE ~20 % of rows were affected.
- **Implausibly-labelled releases removed (class level)**: releases with > 75 % defective classes, evaluated *after* conflict removal. Final run excluded xalan-2.7 (99.8 %), log4j-1.2 (94.2 %), xerces-1.4.4 (90.0 %), velocity-1.5 (77.7 %). (poi-2.5 was 78 % before conflict removal but falls below 75 % after, so it is kept.)
- **+4 class features** (`ce, npm, amc, lcom3`) after an ablation showed +0.02 AUC.
- Evidence (5-fold RF AUC): as-is 0.567 → conflicts removed 0.714 → + releases removed 0.723 → + 4 features 0.743.

### 2.2 Per-file score
- Function units → function model probabilities; class units → class model probabilities.
- File probability = **max** over its units (a file is as risky as its riskiest unit); unit-level detail shown on drill-down.
- If a file has no classes (or is non-Python), only the function model contributes.

### 2.3 Training pipeline
`DataPreprocessor`: load → dedupe → drop NA / inconsistent rows (known NASA MDP cleaning issues) → log1p transform for skewed metrics → `StandardScaler` (inside pipeline) → imbalance strategy.
Candidates: RandomForest, LogisticRegression, MLPClassifier × {SMOTE, class_weight}.
Metrics: accuracy, precision, recall, F1, ROC-AUC (+ PR-AUC, MCC as extras).
Selection: best mean ROC-AUC (tie-break F1); saved with joblib + metadata JSON; results CSV + plots under `docs/results/`.

## 3. Architecture

```
routes (Flask blueprints)  →  services  →  ml / metrics modules  →  DB (SQLAlchemy / SQLite)
```

| Required class | Location | Responsibility |
|---|---|---|
| `User` | `app/models/user.py` | Account, role enum, password hash, Flask-Login mixin |
| `CodeRepository` | `app/services/code_repository.py` (+ DB row `app/models/repository.py`) | Ingest file / ZIP / Git URL into an isolated workspace; zip-slip & size checks; language detection |
| `MetricExtractor` | `app/metrics/metric_extractor.py` | Facade dispatching to `python_metrics.py` (radon + ast OO) and `lizard_metrics.py` |
| `DataPreprocessor` | `app/ml/data_preprocessor.py` | Training data cleaning + identical transform at inference |
| `MLModel` | `app/ml/ml_model.py` | Wraps a fitted pipeline + metadata; train / evaluate / save / load / explain |
| `PredictionEngine` | `app/services/prediction_engine.py` | Loads active models, scores units, aggregates per file, risk label, top contributing metrics |
| `Report` | `app/models/report.py` (+ `app/services/report_service.py`) | Persisted result; HTML / CSV / PDF rendering; run comparison |

Error handling: custom exceptions (`InvalidUploadError`, `EmptyRepositoryError`, `UnsupportedLanguageError`, `ModelNotAvailableError`, `GitCloneError`) mapped to flash messages (`data-testid="flash-error"`) and logged.

## 4. Folder structure

```
defect-predictor/
├── run.py                     # entry point
├── config.py                  # .env-driven config classes (Dev/Test)
├── requirements.txt  .env.example  README.md
├── app/
│   ├── __init__.py            # create_app()
│   ├── extensions.py          # db, login_manager, csrf
│   ├── exceptions.py
│   ├── models/                # SQLAlchemy: user, repository, report, model_version, audit
│   ├── routes/                # auth, main(dashboard), upload, reports, admin, health
│   ├── services/              # code_repository, prediction_engine, report_service, training_service, user_service
│   ├── ml/                    # data_preprocessor, ml_model, trainer, explain
│   ├── metrics/               # metric_extractor, python_metrics, oo_metrics, lizard_metrics, languages
│   ├── templates/             # base + auth/ reports/ admin/ partials/
│   └── static/                # css, js, vendor (bootstrap, chart.js)
├── data/
│   ├── raw/                   # vendored public datasets + SOURCES.md
│   ├── processed/             # generated
│   └── samples/               # small sample code set for demos & tests
├── models/                    # versioned .joblib + .json metadata
├── scripts/                   # download_datasets.py, train.py, seed.py, reset_db.py
├── notebooks/                 # optional exploration
├── docs/                      # PLAN.md, selenium-locators.md, results/
├── logs/
├── instance/                  # sqlite db, uploads, workspaces (git-ignored)
└── tests/
    ├── unit/  integration/
    └── selenium/
        ├── conftest.py        # live server + headless Chrome fixtures
        ├── pages/             # BasePage, LoginPage, UploadPage, ReportPage
        └── tests/             # test_login, test_upload_predict, test_role_access
```

## 5. URLs

| URL | Access |
|---|---|
| `/health` | public (JSON: status, db, active models) |
| `/login`, `/register`, `/logout` | public / authed |
| `/dashboard` | all roles |
| `/upload` | Developer, Admin |
| `/reports` | Dev → own; QA/Admin → all |
| `/reports/<id>`, `/reports/<id>/export.csv`, `/reports/<id>/export.pdf` | owner or QA/Admin (export: QA/Admin + owner) |
| `/reports/compare?a=<id>&b=<id>` | QA, Admin |
| `/admin/users` | Admin |
| `/admin/models` (list, activate, retrain, upload CSV) | Admin |
| `/admin/logs` | Admin |

## 6. Phases & exit criteria

| Phase | Deliverable | Proof |
|---|---|---|
| 1 | Plan, skeleton, venv | deps import OK, git commit |
| 2 | Datasets, preprocessing, training & evaluation | results table (CV mean ± std), stats test, saved models |
| 3 | Metric extractor | extraction on `data/samples/` printed; unit tests |
| 4 | Prediction engine + report generation | CLI run on samples → CSV/PDF produced |
| 5 | Flask app (auth, roles, upload, dashboard, reports, admin) | app runs; manual walkthrough + `/health` |
| 6 | Selenium polish, POM skeleton, 3 tests, locator docs | headless Selenium run green |
| 7 | pytest suite, README, pinned requirements, optional Dockerfile | full test run + coverage |

## 7. Known limitations (to state honestly in the report/paper)
- Cross-project prediction: models trained on NASA (C/Java) and PROMISE (Java) are applied to arbitrary uploaded code; expect domain-shift.
- Non-Python Halstead values are token-based approximations.
- `ev(g)`, `iv(g)` and several CK extensions are excluded for extractability.
