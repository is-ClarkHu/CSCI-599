from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.data import run_data
from app.agents.deps import WorkerInput
from app.data.medals_db import build_db
from tests.fakes import FakeLLM, make_deps


ROW = {"series": "WUGC", "year": "2024", "city": "Gold Coast", "host_country": "Australia",
       "division": "Open", "place": "1", "team": "United States", "team_country": "United States",
       "source_url": "https://en.wikipedia.org/wiki/World_Ultimate_Championships"}


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "m.sqlite"
    build_db([ROW], path)
    return path


@pytest.fixture
def events(monkeypatch):
    seen: list[tuple] = []
    monkeypatch.setattr("app.agents.data.trace", lambda kind, node, **d: seen.append((kind, d)))
    return seen


def inp(final=True):
    return WorkerInput(query="Who won WUGC 2024 open?", category="stats", prior=[], final=final)


async def test_successful_query_answers_with_sql_citation(db, events) -> None:
    llm = FakeLLM({"data": ["SELECT team FROM medals WHERE year = 2024 AND place = 1",
                            "The United States won [S1]."]})
    result = await run_data(inp(), make_deps(llm=llm, medals_db=db))
    assert result["ok"] and result["output"] == "The United States won [S1]."
    assert result["citations"][0]["kind"] == "sql"
    assert "SELECT team" in result["citations"][0]["snippet"]
    assert [c["stream"] for c in llm.calls] == [False, True]
    sql_trace = [d for k, d in events if k == "sql_query"][0]
    assert sql_trace["ok"] and sql_trace["row_count"] == 1
    assert "2024-2024" in llm.calls[0]["messages"][0].content


async def test_zero_rows_escalates_without_streaming(db, events) -> None:
    llm = FakeLLM({"data": ["SELECT team FROM medals WHERE year = 2030"]})
    result = await run_data(inp(), make_deps(llm=llm, medals_db=db))
    assert result["ok"] and result["escalate"] and result["streamed"] is False
    assert "covers 2024-2024" in result["meta"]["reason"]
    assert len(llm.calls) == 1


async def test_no_sql_escalates(db, events) -> None:
    result = await run_data(inp(), make_deps(llm=FakeLLM({"data": ["NO_SQL"]}), medals_db=db))
    assert result["escalate"] is True


async def test_syntax_error_is_retried_once(db, events) -> None:
    llm = FakeLLM({"data": ["SELECT nope FROM medals", "SELECT team FROM medals", "Answer [S1]."]})
    result = await run_data(inp(), make_deps(llm=llm, medals_db=db))
    assert result["ok"] and len(llm.calls) == 3
    assert "no such column" in llm.calls[1]["messages"][-1].content


async def test_second_syntax_error_fails(db, events) -> None:
    llm = FakeLLM({"data": ["SELECT nope FROM medals", "SELECT still_nope FROM medals"]})
    result = await run_data(inp(), make_deps(llm=llm, medals_db=db))
    assert result["ok"] is False


async def test_unsafe_sql_fails_without_retry(db, events) -> None:
    llm = FakeLLM({"data": ["DROP TABLE results"]})
    result = await run_data(inp(), make_deps(llm=llm, medals_db=db))
    assert result["ok"] is False and "unsafe" in result["error"]
    assert len(llm.calls) == 1


async def test_missing_database_fails_gracefully(tmp_path, events) -> None:
    result = await run_data(inp(), make_deps(medals_db=tmp_path / "nope.sqlite"))
    assert result["ok"] is False and result["error"] == "medals database unavailable"


async def test_llm_failure_fails_gracefully(db, events) -> None:
    result = await run_data(inp(), make_deps(llm=FakeLLM(fail={"data"}), medals_db=db))
    assert result["ok"] is False
