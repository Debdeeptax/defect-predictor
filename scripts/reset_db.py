"""Reset the database to the known seed state (for repeatable Selenium runs).

python scripts/reset_db.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.seed import main  # noqa: E402

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "--reset", *sys.argv[1:]]
    sys.exit(main())
