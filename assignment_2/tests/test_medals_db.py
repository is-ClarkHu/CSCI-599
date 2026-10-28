from __future__ import annotations

import sqlite3
from pathlib import Path

from app.data.medals_db import build_db, load_rows, schema_summary, validate_rows


ROOT = Path(__file__).resolve().parents[1]

ROW = {"series": "WUGC", "year": "2024", "city": "Gold Coast", "host_country": "Australia",
       "division": "Open", "place": "1", "team": "United States", "team_country": "United States",
       "source_url": "https://en.wikipedia.org/wiki/World_Ultimate_Championships"}


def test_valid_row_passes() -> None:
    assert validate_rows([ROW]) == []


def test_invalid_rows_are_reported() -> None:
    bad = [
        {**ROW, "series": "XYZ"},
        {**ROW, "place": "4"},
        {**ROW, "division": "Juniors"},
        {**ROW, "source_url": ""},
        {**ROW, "year": "1970"},
    ]
    errors = validate_rows(bad)
    assert len(errors) == 5


def test_duplicate_place_in_same_event_division_is_reported() -> None:
    errors = validate_rows([ROW, {**ROW, "team": "Canada", "team_country": "Canada"}])
    assert any("duplicate" in e for e in errors)


def test_build_db_and_view(tmp_path: Path) -> None:
    db = tmp_path / "m.sqlite"
    build_db([ROW, {**ROW, "place": "2", "team": "Canada", "team_country": "Canada"}], db)
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT medal, team FROM medals ORDER BY place").fetchall()
    assert rows == [("gold", "United States"), ("silver", "Canada")]
    summary = schema_summary(db)
    assert summary["min_year"] == 2024 and summary["max_year"] == 2024
    assert summary["series"] == ["WUGC"] and summary["rows"] == 2
    assert "CREATE VIEW medals" in summary["ddl"]


def test_committed_dataset_is_valid() -> None:
    rows = load_rows(ROOT / "data" / "medals.csv")
    assert len(rows) >= 150
    assert validate_rows(rows) == []
