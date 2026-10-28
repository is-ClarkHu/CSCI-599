from __future__ import annotations

import asyncio
import json
import logging
import sqlite3

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.deps import AgentDeps, WorkerInput
from app.data.medals_db import schema_summary
from app.data.sql_tool import SQLResult, UnsafeSQLError, run_sql, validate_sql
from app.events import trace
from app.llm.router import LLMUnavailableError
from app.types import Citation, WorkerResult


logger = logging.getLogger(__name__)

NO_SQL = "NO_SQL"
MAX_ROWS_FOR_ANSWER = 50

DATA_SQL_PROMPT = """You are the Data agent of an Ultimate (flying disc) assistant. You translate questions
about world championship medals into ONE SQLite SELECT query.

Schema:
{ddl}

Series codes: WUGC = World Ultimate Championships (national teams), WUCC = World Ultimate
Club Championships, WBUC = World Beach Ultimate Championships, WU24 = World Under-24
Ultimate Championships, WJUC = World Junior (U20) Ultimate Championships,
WORLD_GAMES = flying disc at the World Games.
Divisions present: {divisions}
Years covered: {min_year}-{max_year}
Country names are English common names, e.g. 'United States', 'Japan', 'Great Britain'.

Rules:
- Prefer the `medals` view.
- Output only the SQL, no explanation, no Markdown fences.
- Use LIKE with wildcards for team names when the user may abbreviate.
- If the question cannot be answered from this schema, output exactly NO_SQL."""

DATA_ANSWER_PROMPT = """You are the Data agent. Answer the user's question using ONLY the SQL result below.
Cite the database as [S1] once. If the result is truncated, say so. Answer in the same
language as the question, in at most three sentences."""


def _sql_citation(sql: str) -> Citation:
    return Citation(label="S1", kind="sql", ref="medals.sqlite",
                    title="WFDF world championship medal database (curated from Wikipedia/WFDF)",
                    page=None, url=None, snippet=sql[:300])


def _result(ok: bool, *, output: str = "", error: str | None = None, escalate: bool = False,
            streamed: bool = False, citations: list[Citation] | None = None, meta: dict | None = None) -> WorkerResult:
    return WorkerResult(worker="data", ok=ok, output=output, citations=citations or [], error=error,
                        escalate=escalate, streamed=streamed, meta=meta or {})


async def _execute(deps: AgentDeps, sql: str) -> SQLResult:
    return await asyncio.to_thread(run_sql, deps.medals_db, sql)


async def run_data(inp: WorkerInput, deps: AgentDeps) -> WorkerResult:
    try:
        if not deps.medals_db.exists():
            raise FileNotFoundError(deps.medals_db)
        schema = await asyncio.to_thread(schema_summary, deps.medals_db)
    except (OSError, sqlite3.Error):
        logger.exception("Medals database unavailable")
        return _result(False, error="medals database unavailable")

    system = SystemMessage(DATA_SQL_PROMPT.format(ddl=schema["ddl"], divisions=", ".join(schema["divisions"]),
                                                  min_year=schema["min_year"], max_year=schema["max_year"]))
    messages = [system, HumanMessage(inp.query)]
    try:
        sql = (await deps.llm.call("data", messages)).text.strip()
        if sql == NO_SQL:
            return _result(True, escalate=True, meta={"reason": "question not answerable from medals DB"})
        result: SQLResult | None = None
        for attempt in range(2):
            try:
                sql = validate_sql(sql)
                result = await _execute(deps, sql)
                break
            except UnsafeSQLError as exc:
                trace("sql_query", "data", ok=False, sql=sql, error=f"unsafe: {exc}")
                return _result(False, error=f"unsafe SQL rejected: {exc}")
            except sqlite3.Error as exc:
                trace("sql_query", "data", ok=False, sql=sql, error=str(exc), attempt=attempt + 1)
                if attempt == 1:
                    return _result(False, error="SQL failed twice")
                messages = messages + [HumanMessage(f"That SQL failed with: {exc}. Return a corrected query only.")]
                sql = (await deps.llm.call("data", messages)).text.strip()
        assert result is not None
        trace("sql_query", "data", ok=True, sql=sql, row_count=result.row_count, truncated=result.truncated)

        if result.row_count == 0:
            return _result(True, escalate=True, meta={
                "reason": f"no rows in medals DB (covers {schema['min_year']}-{schema['max_year']})", "sql": sql})

        table = json.dumps({"columns": result.columns, "rows": result.rows[:MAX_ROWS_FOR_ANSWER],
                            "truncated": result.truncated or result.row_count > MAX_ROWS_FOR_ANSWER},
                           ensure_ascii=False)
        answer_messages = [SystemMessage(DATA_ANSWER_PROMPT),
                           HumanMessage(f"Question: {inp.query}\nSQL: {sql}\nResult: {table}")]
        reply = await deps.llm.call("data", answer_messages, stream=inp.final)
    except LLMUnavailableError as exc:
        return _result(False, error=str(exc))

    return _result(True, output=reply.text, streamed=inp.final, citations=[_sql_citation(sql)],
                   meta={"sql": sql, "row_count": result.row_count, "provider": reply.provider,
                         "model": reply.model, "fallback": reply.fallback})
