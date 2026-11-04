"""Download public defect datasets into data/raw/ and record provenance.

Sources
-------
* NASA MDP, cleaned version D'' (Shepperd et al., TSE 2013) — function/method level.
  Mirror: https://github.com/klainfo/NASADefectDataset (CleanedData/MDP/D'')
* PROMISE CK-metrics (Jureczko & Madeyski, PROMISE 2010) — class level.
  Mirror: https://github.com/feiwww/PROMISE-backup (bug-data/)

Usage:  python scripts/download_datasets.py [--force]
Stdlib only, so it runs before requirements are installed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
NASA_DIR = RAW / "nasa"
PROMISE_DIR = RAW / "promise"

NASA_BASE = "https://raw.githubusercontent.com/klainfo/NASADefectDataset/master/CleanedData/MDP/D%27%27"
NASA_PROJECTS = ["CM1", "JM1", "KC1", "KC3", "MC1", "MC2", "MW1",
                 "PC1", "PC2", "PC3", "PC4", "PC5"]

PROMISE_TREE = "https://api.github.com/repos/feiwww/PROMISE-backup/git/trees/master?recursive=1"
PROMISE_RAW = "https://raw.githubusercontent.com/feiwww/PROMISE-backup/master/"
CK_REQUIRED = {"wmc", "dit", "noc", "cbo", "rfc", "lcom", "loc", "max_cc", "avg_cc", "bug"}

UA = {"User-Agent": "sdp-dataset-downloader/1.0"}


def fetch(url: str, retries: int = 4) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except Exception as exc:  # network flakiness
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {last}")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def arff_to_rows(text: str) -> tuple[list[str], list[list[str]]]:
    """Minimal ARFF reader (numeric attrs + nominal class). Ignores comments and sparse format."""
    header: list[str] = []
    rows: list[list[str]] = []
    in_data = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%"):
            continue
        low = line.lower()
        if not in_data:
            if low.startswith("@attribute"):
                header.append(line.split()[1].strip("'\""))
            elif low.startswith("@data"):
                in_data = True
            continue
        values = next(csv.reader([line]))
        if len(values) != len(header):
            raise ValueError(f"Row has {len(values)} values, header has {len(header)}")
        rows.append([v.strip() for v in values])
    return header, rows


def download_nasa(force: bool, manifest: list[dict]) -> None:
    NASA_DIR.mkdir(parents=True, exist_ok=True)
    for name in NASA_PROJECTS:
        csv_path = NASA_DIR / f"{name}.csv"
        url = f"{NASA_BASE}/{name}.arff"
        if csv_path.exists() and not force:
            print(f"[nasa] {name}: exists, skipping")
            data = (NASA_DIR / f"{name}.arff").read_bytes()
        else:
            data = fetch(url)
            (NASA_DIR / f"{name}.arff").write_bytes(data)
            header, rows = arff_to_rows(data.decode("utf-8", errors="replace"))
            # Normalise the label column name (JM1 uses 'label', others 'Defective').
            header = ["Defective" if h.lower() in {"label", "defective"} else h for h in header]
            with csv_path.open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(header)
                w.writerows(rows)
            print(f"[nasa] {name}: {len(rows)} rows, {len(header)} cols")
        manifest.append({"dataset": "nasa_mdp_d2", "project": name, "url": url,
                         "file": f"data/raw/nasa/{name}.arff", "sha256": sha256(data)})


def download_promise(force: bool, manifest: list[dict]) -> None:
    PROMISE_DIR.mkdir(parents=True, exist_ok=True)
    tree = json.loads(fetch(PROMISE_TREE))
    paths = sorted(t["path"] for t in tree["tree"]
                   if t["path"].startswith("bug-data/") and t["path"].endswith(".csv"))
    for path in paths:
        fname = Path(path).name
        out = PROMISE_DIR / fname
        url = PROMISE_RAW + path
        if out.exists() and not force:
            data = out.read_bytes()
            print(f"[promise] {fname}: exists, skipping")
        else:
            data = fetch(url)
            header = next(csv.reader(io.StringIO(data.decode("utf-8", errors="replace"))))
            cols = {h.strip().lower() for h in header}
            if not CK_REQUIRED.issubset(cols):
                print(f"[promise] {fname}: missing CK columns {CK_REQUIRED - cols}, skipped")
                continue
            out.write_bytes(data)
            n = data.count(b"\n")
            print(f"[promise] {fname}: ~{n} rows")
        manifest.append({"dataset": "promise_ck", "project": fname[:-4], "url": url,
                         "file": f"data/raw/promise/{fname}", "sha256": sha256(data)})


def write_sources(manifest: list[dict]) -> None:
    (RAW / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    lines = [
        "# Dataset sources",
        "",
        f"Downloaded: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        "## NASA MDP (cleaned D'')",
        "- Shepperd, Song, Sun, Mair. *Data Quality: Some Comments on the NASA Software Defect Datasets.* IEEE TSE 39(9), 2013.",
        "- Mirror: https://github.com/klainfo/NASADefectDataset (`CleanedData/MDP/D''`)",
        "- Granularity: function/method. Label: `Defective` (Y/N).",
        "",
        "## PROMISE CK metrics",
        "- Jureczko, Madeyski. *Towards identifying software project clusters with regard to defect prediction.* PROMISE 2010.",
        "- Mirror: https://github.com/feiwww/PROMISE-backup (`bug-data/`)",
        "- Granularity: Java class. Label: `bug` (count; >0 ⇒ defective).",
        "",
        "## Files (sha256)",
        "",
        "| dataset | project | sha256 |",
        "|---|---|---|",
    ]
    lines += [f"| {m['dataset']} | {m['project']} | `{m['sha256'][:16]}…` |" for m in manifest]
    (RAW / "SOURCES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-download even if present")
    args = ap.parse_args()
    manifest: list[dict] = []
    download_nasa(args.force, manifest)
    download_promise(args.force, manifest)
    write_sources(manifest)
    print(f"Done: {len(manifest)} files recorded in data/raw/manifest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
