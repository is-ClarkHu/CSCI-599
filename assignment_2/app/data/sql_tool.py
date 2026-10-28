from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|PRAGMA|VACUUM|REINDEX|TRIGGER)\b",
    re.IGNORECASE,
)


class UnsafeSQLError(ValueError):
    pass


@dataclass
class SQLResult:
    columns: list[str]
    rows: list[list]
    row_count: int
    truncated: bool


def validate_sql(sql: str) -> str:
    cleaned = re.sub(r"^```(?:sql)?\s*|\s*```$", "", sql.strip(), flags=re.IGNORECASE).strip()
    cleaned = cleaned.rstrip(";").strip()
    if not cleaned:
        raise UnsafeSQLError("empty SQL")
    if not re.match(r"^(SELECT|WITH)\b", cleaned, re.IGNORECASE):
        raise UnsafeSQLError("only SELECT/WITH queries are allowed")
    if ";" in cleaned:
        raise UnsafeSQLError("multiple statements are not allowed")
    if FORBIDDEN.search(cleaned):
        raise UnsafeSQLError("write or administrative keywords are not allowed")
    return cleaned


def run_sql(db_path: Path, sql: str, max_rows: int = 200, timeout_ms: int = 2000) -> SQLResult:
    statement = validate_sql(sql)
    deadline = time.monotonic() + timeout_ms / 1000
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only = ON")
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
        cursor = conn.execute(statement)
        columns = [d[0] for d in cursor.description or []]
        fetched = cursor.fetchmany(max_rows + 1)
    finally:
        conn.close()
    truncated = len(fetched) > max_rows
    rows = [list(r) for r in fetched[:max_rows]]
    return SQLResult(columns=columns, rows=rows, row_count=len(rows), truncated=truncated)
