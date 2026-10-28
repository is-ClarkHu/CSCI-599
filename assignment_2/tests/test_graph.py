from __future__ import annotations

import json
from pathlib import Path

from app.agents.research import run_research
from app.data.medals_db import build_db
from app.graph.builder import FAILURE_MESSAGE, OFF_TOPIC_MESSAGE, build_graph
from tests.fakes import FakeLLM, FakeStore, FakeTavily, chunk, make_deps


def plan(category, steps):
    return json.dumps({"category": category, "plan": steps, "reason": "test"})


async def run(graph, query="q"):
    events, final = [], {}
    async for mode, item in graph.astream({"query": query, "results": []}, stream_mode=["custom", "values"]):
        if mode == "custom":
            events.append(item)
        else:
            final = item
    return events, final


def traces(events, kind=None):
    return [e["data"] for e in events if e["event"] == "trace" and (kind is None or e["data"]["kind"] == kind)]


async def test_rules_question_flows_through_research() -> None:
    llm = FakeLLM({"supervisor": [plan("rules", ["research"])], "research": ["Ten seconds [S1]."]})
    deps = make_deps(llm=llm, store=FakeStore([chunk("wfdf-rules-2025:p3:c0", 0.9)]))
    events, final = await run(build_graph(deps))
    assert final["final_answer"] == "Ten seconds [S1]."
    route = traces(events, "agent_route")[0]
    assert route["plan"] == ["research"] and route["planner"] == "llm"
    assert [t["next"] for t in traces(events, "transition") if t["node"] == "dispatch"] == ["research", "finalize"]
    assert [e["data"]["label"] for e in events if e["event"] == "citation"] == ["S1"]
    assert llm.calls[-1]["stream"] is True


async def test_off_topic_runs_no_worker() -> None:
    llm = FakeLLM({"supervisor": [plan("off_topic", [])]})
    events, final = await run(build_graph(make_deps(llm=llm)))
    assert final["final_answer"] == OFF_TOPIC_MESSAGE
    assert traces(events, "transition")[0]["reason"] == "off-topic, no worker"
    assert [c["agent"] for c in llm.calls] == ["supervisor"]
    assert any(e["event"] == "token" and e["data"]["text"] == OFF_TOPIC_MESSAGE for e in events)


async def test_stats_miss_escalates_to_research_web(tmp_path: Path) -> None:
    db = tmp_path / "m.sqlite"
    build_db([{"series": "WUGC", "year": "2024", "city": "", "host_country": "", "division": "Open", "place": "1",
               "team": "United States", "team_country": "United States", "source_url": "https://x"}], db)
    tavily = FakeTavily(search_results=[{"title": "WUCC 2026", "url": "https://n", "content": "X won"}])
    llm = FakeLLM({"supervisor": [plan("news", ["data"])],
                   "data": ["SELECT team FROM medals WHERE year = 2026"],
                   "research": ["X won [S1]."]})
    deps = make_deps(llm=llm, store=FakeStore([]), tavily=tavily, medals_db=db)
    events, final = await run(build_graph(deps))
    hops = [t for t in traces(events, "transition") if t["node"] == "dispatch"]
    assert [h["next"] for h in hops] == ["data", "research", "finalize"]
    assert "escalating to research" in hops[1]["reason"]
    assert tavily.calls == [("search", "research"), ("extract", "research")]
    assert final["final_answer"] == "X won [S1]."


async def test_research_then_summary_streams_only_summary() -> None:
    llm = FakeLLM({"supervisor": [plan("rules", ["research", "summary"])],
                   "research": ["Draft [S1]."], "summary": ["- Short [S1]"]})
    deps = make_deps(llm=llm, store=FakeStore([chunk("wfdf-rules-2025:p3:c0", 0.9)]))
    events, final = await run(build_graph(deps))
    streams = {c["agent"]: c["stream"] for c in llm.calls}
    assert streams == {"supervisor": False, "research": False, "summary": True}
    assert final["final_answer"] == "- Short [S1]"


async def test_summary_failure_returns_research_draft_as_tokens() -> None:
    llm = FakeLLM({"supervisor": [plan("rules", ["research", "summary"])], "research": ["Draft [S1]."]},
                  fail={"summary"})
    deps = make_deps(llm=llm, store=FakeStore([chunk("wfdf-rules-2025:p3:c0", 0.9)]))
    events, final = await run(build_graph(deps))
    assert final["final_answer"] == "Draft [S1]."
    assert any(e["event"] == "token" and e["data"]["text"] == "Draft [S1]." for e in events)
    assert traces(events, "worker_error")[0]["node"] == "summary"


async def test_unexpected_worker_exception_does_not_crash_graph() -> None:
    async def exploding(inp, deps):
        raise KeyError("bug")

    llm = FakeLLM({"supervisor": [plan("rules", ["research"])]})
    graph = build_graph(make_deps(llm=llm), workers={"research": exploding, "data": exploding, "summary": exploding})
    events, final = await run(graph)
    assert final["final_answer"] == FAILURE_MESSAGE
    assert "KeyError" in traces(events, "worker_error")[0]["error"]


async def test_planner_failure_uses_fallback_plan() -> None:
    llm = FakeLLM({"research": ["A [S1]."]}, fail={"supervisor"})
    deps = make_deps(llm=llm, store=FakeStore([chunk("wfdf-rules-2025:p3:c0", 0.9)]))
    events, final = await run(build_graph(deps))
    assert traces(events, "agent_route")[0]["planner"] == "fallback"
    assert final["final_answer"] == "A [S1]."
