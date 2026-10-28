from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.data.medals_db import build_db, load_rows, validate_rows


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    rows = load_rows(ROOT / "data" / "medals.csv")
    errors = validate_rows(rows)
    if errors:
        print("\n".join(errors))
        return 1
    db = Settings().medals_db
    build_db(rows, db)
    print(f"built {db} with {len(rows)} result rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
