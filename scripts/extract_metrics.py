"""Print (or save) extracted metrics for a source directory.

python scripts/extract_metrics.py data/samples/sample_project [--csv out_prefix]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from app.exceptions import SDPError  # noqa: E402
from app.metrics.metric_extractor import MetricExtractor  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--csv", help="write <prefix>_functions.csv / <prefix>_classes.csv")
    args = ap.parse_args()
    try:
        res = MetricExtractor().extract(args.path)
    except SDPError as exc:
        print(f"ERROR ({type(exc).__name__}): {exc.user_message}")
        return 2

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 30)
    print(f"Files analysed: {len(res.files)}  languages: {res.languages}  "
          f"skipped: {res.skipped_count}")
    for s in res.skipped:
        print(f"  skipped {s['path']}: {s['reason']}")
    for w in res.warnings:
        print(f"  WARNING: {w}")

    print("\nPer-file summary")
    print(pd.DataFrame([{"file": f.path, "lang": f.language, "partial": f.partial, **f.summary}
                        for f in res.files]).to_string(index=False))

    fn = pd.DataFrame(res.function_rows())
    cols = ["file", "unit", "loc_total", "loc_executable", "cyclomatic_complexity",
            "halstead_n1", "halstead_n2", "halstead_N1", "halstead_N2", "halstead_volume"]
    print(f"\nFunction-level units ({len(fn)})")
    print(fn[cols].round(1).to_string(index=False))

    cl = pd.DataFrame(res.class_rows())
    if not cl.empty:
        print(f"\nClass-level units ({len(cl)})")
        print(cl.drop(columns=["start_line"]).round(2).to_string(index=False))

    if args.csv:
        fn.to_csv(f"{args.csv}_functions.csv", index=False)
        cl.to_csv(f"{args.csv}_classes.csv", index=False)
        print(f"\nSaved {args.csv}_functions.csv / {args.csv}_classes.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
