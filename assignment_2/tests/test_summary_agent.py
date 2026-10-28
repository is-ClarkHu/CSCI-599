from __future__ import annotations

import pytest

from app.agents.deps import WorkerInput
from app.agents.summary import run_summary
from tests.fakes import FakeLLM, FakeTavily, make_deps


def research_result(citations):
    return {"worker": "research", "ok": True, "output": "Draft with [S1] and [S2].", "citations": citations,
            "error": None, "escalate": False, "streamed": False, "meta": {}}


RAG = {"label": "S1", "kind": "rag", "ref": "wfdf-rules-2025:p1:c0", "title": "WFDF", "page": 1,
       "url": "https://w", "snippet": "rule text"}
WEB = {"label": "S2", "kind": "web", "ref": "https://n", "title": "News", "page": None,
       "url": "https://n", "snippet": "short"}


@pytest.fixture
def events(monkeypatch):
    seen: list[tuple] = []
    monkeypatch.setattr("app.agents.summary.trace", lambda kind, node, **d: seen.append((kind, d)))
    return seen


def inp(prior, final=True):
    return WorkerInput(query="Summarize the stall rules", category="rules", prior=prior, final=final)


async def test_summarizes_previous_result_and_keeps_citations(events) -> None:
    llm = FakeLLM({"summary": ["- Ten seconds [S1]"]})
    result = await run_summary(inp([research_result([RAG])]), make_deps(llm=llm))
    assert result["ok"] and result["output"] == "- Ten seconds [S1]"
    assert result["citations"] == [RAG] and result["meta"]["source_worker"] == "research"
    human = llm.calls[0]["messages"][-1].content
    assert "Draft with [S1] and [S2]." in human and "[S1] WFDF" in human
    assert llm.calls[0]["stream"] is True
    received = [d for kind, d in events if kind == "transition"][0]
    assert received["source_worker"] == "research" and received["source_labels"] == ["S1"]
    assert received["draft_chars"] == len("Draft with [S1] and [S2].")


async def test_web_sources_are_extracted_through_shared_mcp(events) -> None:
    tavily = FakeTavily(extract_results=[{"url": "https://n", "content": "full article text"}])
    llm = FakeLLM()
    result = await run_summary(inp([research_result([RAG, WEB])]), make_deps(llm=llm, tavily=tavily))
    assert tavily.calls == [("extract", "summary")]
    assert result["meta"]["extracted_urls"] == ["https://n"]
    assert "full article text" in llm.calls[0]["messages"][-1].content


async def test_no_extract_when_only_rag_sources(events) -> None:
    tavily = FakeTavily()
    await run_summary(inp([research_result([RAG])]), make_deps(tavily=tavily))
    assert tavily.calls == []


async def test_nothing_to_summarize(events) -> None:
    failed = {**research_result([]), "ok": False, "output": ""}
    result = await run_summary(inp([failed]), make_deps())
    assert result["ok"] is False and result["error"] == "nothing to summarize"


async def test_llm_failure(events) -> None:
    result = await run_summary(inp([research_result([RAG])]), make_deps(llm=FakeLLM(fail={"summary"})))
    assert result["ok"] is False
