# Software Defect Prediction System

Web app that extracts static code metrics from submitted source code (file, ZIP or Git URL), runs trained ML models, and reports defect-proneness per file.

> Work in progress — see [docs/PLAN.md](docs/PLAN.md) for the design and phase plan. Full setup/run instructions arrive in Phase 7.

## Quick setup (dev)

```powershell
& "C:\Program Files\Python311\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
```
