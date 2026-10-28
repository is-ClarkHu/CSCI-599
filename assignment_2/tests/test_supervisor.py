from __future__ import annotations

import pytest

from app.graph.supervisor import MAX_WORKER_RUNS, decide_next, make_plan, parse_plan
from tests.fakes import FakeLLM


def res(worker, ok=True, escalate=False, error=None, reason=None):
    return {"worker": worker, "ok": ok, "output": "x" if ok else "", "citations": [], "error": error,
            "escalate": escalate, "streamed": False, "meta": {"reason": reason} if reason else {}}


# ---- parse_plan ----

def test_parse_plain_json() -> None:
    plan = parse_plan('{"category": "rules", "plan": ["research"], "reason": "r"}')
    assert (plan.category, plan.plan, plan.reason, plan.source) == ("rules", ["research"], "r", "llm")


def test_parse_fenced_json_and_dedupe() -> None:
    plan = parse_plan('```json\n{"category":"rules","plan":["research","research","summary"],"reason":"r"}\n```')
    assert plan.plan == ["research", "summary"]


def test_summary_first_gets_research_prepended() -> None:
    assert parse_plan('{"category":"rules","plan":["summary"],"reason":"r"}').plan == ["research", "summary"]


def test_off_topic_forces_empty_plan() -> None:
    assert parse_plan('{"category":"off_topic","plan":["research"],"reason":"r"}').plan == []


def test_empty_plan_gets_category_default() -> None:
    assert parse_plan('{"category":"stats","plan":[],"reason":"r"}').plan == ["data"]


def test_unknown_workers_are_dropped_and_plan_capped() -> None:
    plan = parse_plan('{"category":"rules","plan":["code","research","data","summary","research"],"reason":"r"}')
    assert plan.plan == ["research", "data", "summary"]


@pytest.mark.parametrize("text", ["not json", '{"category":"weird","plan":[],"reason":"r"}', "{}"])
def test_invalid_plans_raise(text: str) -> None:
    with pytest.raises(ValueError):
        parse_plan(text)


async def test_make_plan_falls_back_on_garbage() -> None:
    plan = await make_plan("q", FakeLLM({"supervisor": ["garbage"]}))
    assert plan.source == "fallback" and plan.plan == ["research"] and plan.category == "rules"


async def test_make_plan_falls_back_on_llm_failure() -> None:
    plan = await make_plan("q", FakeLLM(fail={"supervisor"}))
    assert plan.source == "fallback" and "planner unavailable" in plan.reason


# ---- decide_next ----

def test_off_topic_goes_straight_to_finalize() -> None:
    d = decide_next("off_topic", [], 0, [])
    assert (d.next_node, d.reason) == ("finalize", "off-topic, no worker")


def test_follows_plan_in_order() -> None:
    d = decide_next("rules", ["research", "summary"], 0, [])
    assert (d.next_node, d.cursor, d.reason) == ("research", 1, "next planned worker 1/2")
    d = decide_next("rules", ["research", "summary"], 1, [res("research")])
    assert (d.next_node, d.cursor) == ("summary", 2)
    d = decide_next("rules", ["research", "summary"], 2, [res("research"), res("summary")])
    assert (d.next_node, d.reason) == ("finalize", "plan complete")


def test_data_escalation_inserts_research() -> None:
    d = decide_next("news", ["data"], 1, [res("data", escalate=True, reason="no rows in medals DB (covers 1983-2024)")])
    assert d.next_node == "research" and d.plan == ["data", "research"] and d.cursor == 2
    assert d.reason.startswith("no rows in medals DB") and "escalating to research" in d.reason


def test_data_failure_falls_back_to_research() -> None:
    d = decide_next("stats", ["data"], 1, [res("data", ok=False, error="SQL failed twice")])
    assert d.next_node == "research" and "data failed (SQL failed twice)" in d.reason


def test_research_failure_skips_summary() -> None:
    d = decide_next("rules", ["research", "summary"], 1, [res("research", ok=False, error="boom")])
    assert d.next_node == "finalize" and d.plan == ["research"]
    assert d.reason == "research failed (boom); skipping summary"


def test_research_failure_keeps_other_independent_workers() -> None:
    d = decide_next("stats", ["research", "data"], 1, [res("research", ok=False, error="boom")])
    assert d.next_node == "data" and "skipping summary" in d.reason


def test_summary_failure_returns_draft() -> None:
    d = decide_next("rules", ["research", "summary"], 2, [res("research"), res("summary", ok=False, error="e")])
    assert d.next_node == "finalize" and "returning previous draft" in d.reason


def test_no_second_research_after_escalation() -> None:
    results = [res("data", escalate=True, reason="none"), res("research", escalate=False)]
    d = decide_next("news", ["data", "research"], 2, results)
    assert d.next_node == "finalize"


def test_step_limit() -> None:
    d = decide_next("rules", ["research"] * 3, 0, [res("research")] * MAX_WORKER_RUNS)
    assert (d.next_node, d.reason) == ("finalize", "step limit reached")
