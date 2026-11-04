"""(Re)build data/samples/sample_project.zip from data/samples/sample_project/.

Used for manual demos and Selenium upload tests:  python scripts/make_sample_zip.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.seed import sample_zip_bytes  # noqa: E402

OUT = ROOT / "data" / "samples" / "sample_project.zip"

if __name__ == "__main__":
    OUT.write_bytes(sample_zip_bytes())
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes)")
