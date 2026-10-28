from __future__ import annotations

from pathlib import Path

import pytest

from app.data.medals_db import build_db
from app.data.sql_tool import UnsafeSQLError, run_sql, validate_sql


ROW = {"series": "WUGC", "year": "2024", "city": "Gold Coast", "host_country": "Australia",
       "division": "Open", "place": "1", "team": "United States", "team_country": "United States",
       "source_url": "https://en.wikipedia.org/wiki/World_Ultimate_Championships"}


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "m.sqlite"
    build_db([ROW, {**ROW, "place": "2", "team": "Canada", "team_country": "Canada"}], path)
    return path


def test_strips_fences_and_trailing_semicolon() -> None:
    assert validate_sql("```sql\nSELECT 1;\n```") == "SELECT 1"


@pytest.mark.parametrize("sql", [
    "DROP TABLE results",
    "SELECT 1; DROP TABLE results",
    "PRAGMA table_info(results)",
    "ATTACH DATABASE 'x' AS y",
    "UPDATE results SET team='x'",
    "",
])
def test_rejects_unsafe_sql(sql: str) -> None:
    with pytest.raises(UnsafeSQLError):
        validate_sql(sql)


def test_allows_with_clause() -> None:
    assert validate_sql("WITH t AS (SELECT 1) SELECT * FROM t").startswith("WITH")


def test_run_sql_returns_rows(db: Path) -> None:
    result = run_sql(db, "SELECT team, medal FROM medals ORDER BY place")
    assert result.columns == ["team", "medal"]
    assert result.rows == [["United States", "gold"], ["Canada", "silver"]]
    assert result.row_count == 2 and result.truncated is False


def test_run_sql_truncates(db: Path) -> None:
    result = run_sql(db, "SELECT * FROM medals", max_rows=1)
    assert result.row_count == 1 and result.truncated is True


def test_database_is_read_only_even_if_validation_is_bypassed(db: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.data.sql_tool.validate_sql", lambda sql: sql)
    with pytest.raises(Exception):
        run_sql(db, "DELETE FROM results")
    assert run_sql(db, "SELECT COUNT(*) FROM results").rows == [[2]]


def test_syntax_error_raises_sqlite_error(db: Path) -> None:
    import sqlite3
    with pytest.raises(sqlite3.Error):
        run_sql(db, "SELECT nope FROM medals")
