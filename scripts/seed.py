"""Create seed users (dev/qa/admin @test.com, password Test@1234) and a sample report.

python scripts/seed.py            # idempotent
python scripts/seed.py --reset    # drop all tables first (same as: flask --app run reset-db)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.seed import seed_all  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="drop and re-create all tables first")
    ap.add_argument("--no-report", action="store_true", help="skip the sample report")
    args = ap.parse_args()
    app = create_app()
    with app.app_context():
        if args.reset:
            db.drop_all()
            db.create_all()
            print("Database reset.")
        for line in seed_all(with_report=not args.no_report):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
