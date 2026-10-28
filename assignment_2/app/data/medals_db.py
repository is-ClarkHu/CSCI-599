from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


ALLOWED_SERIES = frozenset({"WUGC", "WUCC", "WBUC", "WU24", "WJUC", "WORLD_GAMES"})
ALLOWED_DIVISIONS = frozenset({
    "Open", "Women", "Mixed", "Open Masters", "Women's Masters", "Mixed Masters",
    "Open Grand Masters", "Women's Grand Masters", "Mixed Grand Masters", "Open Great Grand Masters",
})

DDL = """CREATE TABLE events (
  event_id     TEXT PRIMARY KEY,
  series       TEXT NOT NULL,
  year         INTEGER NOT NULL,
  city         TEXT,
  host_country TEXT
);
CREATE TABLE results (
  event_id     TEXT NOT NULL REFERENCES events(event_id),
  division     TEXT NOT NULL,
  place        INTEGER NOT NULL CHECK (place IN (1, 2, 3)),
  team         TEXT NOT NULL,
  team_country TEXT NOT NULL,
  source_url   TEXT NOT NULL,
  PRIMARY KEY (event_id, division, place)
);
CREATE VIEW medals AS
  SELECT e.series, e.year, e.city, e.host_country, r.division, r.place,
         CASE r.place WHEN 1 THEN 'gold' WHEN 2 THEN 'silver' ELSE 'bronze' END AS medal,
         r.team, r.team_country
  FROM results r JOIN events e USING (event_id);"""


def load_rows(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def validate_rows(rows: list[dict]) -> list[str]:
    errors: list[str] = []
    seen: set[tuple[str, str, str, str]] = set()
    for line, row in enumerate(rows, start=2):
        if row.get("series") not in ALLOWED_SERIES:
            errors.append(f"line {line}: unknown series {row.get('series')!r}")
        if row.get("division") not in ALLOWED_DIVISIONS:
            errors.append(f"line {line}: unknown division {row.get('division')!r}")
        if row.get("place") not in {"1", "2", "3"}:
            errors.append(f"line {line}: place must be 1, 2 or 3")
        if not (row.get("year", "").isdigit() and 1983 <= int(row["year"]) <= 2030):
            errors.append(f"line {line}: year out of range")
        if not row.get("source_url", "").startswith("https://"):
            errors.append(f"line {line}: missing source_url")
        if not row.get("team") or not row.get("team_country"):
            errors.append(f"line {line}: missing team/team_country")
        key = (row.get("series", ""), row.get("year", ""), row.get("division", ""), row.get("place", ""))
        if key in seen:
            errors.append(f"line {line}: duplicate place {key}")
        seen.add(key)
    return errors


def build_db(rows: list[dict], db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(DDL)
        for row in rows:
            event_id = f"{row['series']}-{row['year']}"
            conn.execute(
                "INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?)",
                (event_id, row["series"], int(row["year"]), row.get("city") or None, row.get("host_country") or None),
            )
            conn.execute(
                "INSERT INTO results VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, row["division"], int(row["place"]), row["team"], row["team_country"], row["source_url"]),
            )


def schema_summary(db_path: Path) -> dict:
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        series = [r[0] for r in conn.execute("SELECT DISTINCT series FROM events ORDER BY series")]
        divisions = [r[0] for r in conn.execute("SELECT DISTINCT division FROM results ORDER BY division")]
        min_year, max_year = conn.execute("SELECT MIN(year), MAX(year) FROM events").fetchone()
        count = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    return {"ddl": DDL, "series": series, "divisions": divisions,
            "min_year": min_year, "max_year": max_year, "rows": count}
