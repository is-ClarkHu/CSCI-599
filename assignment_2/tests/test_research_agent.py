from __future__ import annotations

import pytest

from app.agents.deps import WorkerInput
from app.agents.research import run_research
from tests.fakes import FakeLLM, FakeStore, FakeTavily, chunk, make_deps


@pytest.fixture
def events(monkeypatch):
    seen: list[tuple] = []
    monkeypatch.setattr("app.agents.research.trace", lambda kind, node, **d: seen.append((kind, d)))
    monkeypatch.setattr("app.agents.research.token", lambda text, node: seen.append(("token", text)))
    return seen


def inp(category="rules", prior=None, final=True, query="How long is the stall count?"):
    return WorkerInput(query=query, category=category, prior=prior or [], final=final)


async def test_relevant_rules_question_uses_rag_only(events) -> None:
    tavily = FakeTavily(search_results=[{"title": "x", "url": "https://x", "content": "y"}])
    llm = FakeLLM({"research": ["Ten seconds [S1]."]})
    deps = make_deps(llm=llm, store=FakeStore([chunk("wfdf-rules-2025:p1:c0", 0.8)]), tavily=tavily)
    result = await run_research(inp(), deps)
    assert result["ok"] and result["output"] == "Ten seconds [S1]."
    assert tavily.calls == []
    assert llm.calls[0]["stream"] is True and result["streamed"] is True
    retrieval = [d for k, d in events if k == "rag_retrieval"][0]
    assert retrieval["web_needed"] is False and "sufficient" in retrieval["web_reason"]
    assert result["meta"]["contexts"] == ["The stall count is ten seconds."]


async def test_low_relevance_triggers_web_search(events) -> None:
    tavily = FakeTavily(search_results=[{"title": "News", "url": "https://n", "content": "c"}])
    deps = make_deps(store=FakeStore([chunk("wfdf-rules-2025:p1:c0", 0.1)]), tavily=tavily)
    result = await run_research(inp(), deps)
    assert tavily.calls == [("search", "research"), ("extract", "research")]
    assert result["meta"]["web_used"] is True
    assert [c["kind"] for c in result["citations"]] == ["rag", "web"]


async def test_web_top_result_full_text_comes_from_shared_extract_tool(events) -> None:
    tavily = FakeTavily(search_results=[{"title": "News", "url": "https://n", "content": "short"}],
                        extract_results=[{"url": "https://n", "content": "FULL ARTICLE TEXT"}])
    llm = FakeLLM()
    deps = make_deps(llm=llm, store=FakeStore([]), tavily=tavily)
    result = await run_research(inp(category="news"), deps)
    assert result["meta"]["extracted_urls"] == ["https://n"]
    assert "FULL ARTICLE TEXT" in llm.calls[0]["messages"][-1].content


async def test_news_category_drops_irrelevant_chunks(events) -> None:
    tavily = FakeTavily(search_results=[{"title": "News", "url": "https://n", "content": "c"}])
    deps = make_deps(store=FakeStore([chunk("wfdf-rules-2025:p1:c0", 0.2)]), tavily=tavily)
    result = await run_research(inp(category="news"), deps)
    assert [c["kind"] for c in result["citations"]] == ["web"]


async def test_escalation_from_data_forces_web(events) -> None:
    tavily = FakeTavily(search_results=[{"title": "R", "url": "https://r", "content": "c"}])
    prior = [{"worker": "data", "ok": True, "output": "", "citations": [], "error": None,
              "escalate": True, "streamed": False, "meta": {}}]
    deps = make_deps(store=FakeStore([chunk("wfdf-rules-2025:p1:c0", 0.9)]), tavily=tavily)
    await run_research(inp(category="stats", prior=prior), deps)
    assert tavily.calls == [("search", "research"), ("extract", "research")]


async def test_no_context_and_no_web_skips_llm(events) -> None:
    llm = FakeLLM()
    deps = make_deps(llm=llm, store=FakeStore([]), tavily=FakeTavily(available=False))
    result = await run_research(inp(), deps)
    assert llm.calls == [] and result["ok"] and result["meta"]["no_context"] is True
    assert any(kind == "token" for kind, _ in events)


async def test_broken_store_still_answers_from_web(events) -> None:
    tavily = FakeTavily(search_results=[{"title": "W", "url": "https://w", "content": "c"}])
    deps = make_deps(store=FakeStore(fail=True), tavily=tavily)
    result = await run_research(inp(), deps)
    assert result["ok"] and result["meta"]["web_used"] is True
    retrieval = [d for k, d in events if k == "rag_retrieval"][0]
    assert retrieval["ok"] is False


async def test_web_disabled_setting_is_respected(events) -> None:
    tavily = FakeTavily(search_results=[{"title": "W", "url": "https://w", "content": "c"}])
    deps = make_deps(store=FakeStore([chunk("wfdf-rules-2025:p1:c0", 0.1)]), tavily=tavily, web_enabled=False)
    await run_research(inp(), deps)
    assert tavily.calls == []


async def test_llm_failure_returns_failed_result(events) -> None:
    deps = make_deps(llm=FakeLLM(fail={"research"}), store=FakeStore([chunk("wfdf-rules-2025:p1:c0", 0.9)]))
    result = await run_research(inp(), deps)
    assert result["ok"] is False and "all providers failed" in result["error"]


async def test_not_final_does_not_stream(events) -> None:
    llm = FakeLLM()
    deps = make_deps(llm=llm, store=FakeStore([chunk("wfdf-rules-2025:p1:c0", 0.9)]))
    result = await run_research(inp(final=False), deps)
    assert llm.calls[0]["stream"] is False and result["streamed"] is False
