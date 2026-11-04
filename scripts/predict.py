"""Analyse code from the command line: ingest -> extract -> predict -> report.

python scripts/predict.py data/samples/sample_project
python scripts/predict.py project.zip --pdf report.pdf --csv report.csv
python scripts/predict.py --git https://github.com/owner/repo --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Config  # noqa: E402
from app.exceptions import SDPError  # noqa: E402
from app.metrics.metric_extractor import MetricExtractor  # noqa: E402
from app.services.code_repository import CodeRepository  # noqa: E402
from app.services.prediction_engine import PredictionEngine  # noqa: E402
from app.services.report_service import ReportService  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("path", nargs="?", type=Path, help="directory, source file or .zip")
    ap.add_argument("--git", help="public https Git URL instead of a path")
    ap.add_argument("--csv", type=Path)
    ap.add_argument("--units-csv", type=Path)
    ap.add_argument("--pdf", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    if not args.path and not args.git:
        ap.error("give a path or --git URL")

    repo = CodeRepository.from_config(Config)
    ws = None
    try:
        if args.git:
            ws = repo.from_git(args.git)
            root, source = ws.path, args.git
        elif args.path.is_dir():
            root, source = args.path, str(args.path)
        else:
            with open(args.path, "rb") as fh:
                ws = repo.from_upload(args.path.name, fh)
            root, source = ws.path, args.path.name

        extraction = MetricExtractor(Config.MAX_FILES_PER_ANALYSIS).extract(root)
        payload = PredictionEngine.from_config(Config).predict(extraction)
    except SDPError as exc:
        print(f"ERROR ({type(exc).__name__}): {exc.user_message}")
        return 2
    finally:
        if ws is not None:
            repo.cleanup(ws)

    s = payload["summary"]
    print(f"{s['files']} files, {s['units']} units scored in {s['elapsed_sec']} s | "
          f"risk {s['risk_counts']} | exact SHAP for {s['exact_explanations']} driver units")
    for w in payload["warnings"]:
        print(f"  note: {w}")
    print(f"\n{'#':>3} {'risk':<6} {'prob':>6}  {'file':<34} driving unit / top metrics")
    for f in payload["files"]:
        d = f["driver"] or {}
        print(f"{f['rank']:>3} {f['risk']:<6} {f['probability']:>6.3f}  {f['path']:<34} "
              f"{d.get('unit', '-')} (line {d.get('start_line', '-')})")
        for m in f["top_metrics"][:3]:
            print(f"{'':>53}{m['label']} = {m['value']:g}  ({m['contribution']:+.3f})")

    if args.csv:
        args.csv.write_text(ReportService.to_csv(payload), encoding="utf-8")
    if args.units_csv:
        args.units_csv.write_text(ReportService.to_csv(payload, "unit"), encoding="utf-8")
    if args.pdf:
        args.pdf.write_bytes(ReportService.to_pdf(payload, source=source, author="CLI"))
    if args.json:
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    for p in (args.csv, args.units_csv, args.pdf, args.json):
        if p:
            print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
