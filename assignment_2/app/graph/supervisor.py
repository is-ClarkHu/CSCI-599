from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm.router import LLMUnavailableError
from app.types import Category, WorkerName, WorkerResult


logger = logging.getLogger(__name__)

CATEGORIES: tuple[str, ...] = ("rules", "stats", "news", "off_topic")
WORKERS: tuple[str, ...] = ("research", "data", "summary")
DEFAULT_PLAN: dict[str, list[str]] = {"rules": ["research"], "news": ["research"], "stats": ["data"], "off_topic": []}
MAX_PLAN_LENGTH = 3
MAX_WORKER_RUNS = 4

SUPERVISOR_PROMPT = """You are the Supervisor of an Ultimate (flying disc) assistant. Classify the user's
question and plan which specialist agents to run, in order.

Agents:
- research: answers from the official WFDF / USA Ultimate rulebooks (vector search) and,
  when needed, live web search. Use for rules, spirit of the game, officiating, and for
  current news / upcoming or very recent events.
- data: runs SQL over a database of WFDF world championship medals (WUGC, WUCC, beach,
  U24, U20, World Games). Use for "who won", medal counts, rankings, history.
- summary: condenses the previous agent's answer into short bullet points with citations.
  Add it ONLY when the user asks for a summary, overview, comparison, or "explain simply".

Categories: rules, stats, news, off_topic. A question is off_topic when it is not about
ultimate / flying disc sports at all.

Return ONLY JSON: {"category": "...", "plan": ["..."], "reason": "<one sentence>"}

Examples:
Q: How long is the stall count in WFDF rules?
{"category": "rules", "plan": ["research"], "reason": "Rules question answerable from the rulebook."}
Q: Summarize the differences between WFDF and USA Ultimate foul rules.
{"category": "rules", "plan": ["research", "summary"], "reason": "Rules comparison that the user wants summarized."}
Q: How many gold medals has Japan won at WUGC?
{"category": "stats", "plan": ["data"], "reason": "Medal history lives in the championship database."}
Q: Who won the open final at WUCC 2026 last weekend?
{"category": "news", "plan": ["data"], "reason": "Check the medal database first; dispatcher escalates to web if absent."}
Q: What is the latest WFDF news this week?
{"category": "news", "plan": ["research"], "reason": "Current events need live web search."}
Q: Summarize the latest WFDF news this month in three bullet points.
{"category": "news", "plan": ["research", "summary"], "reason": "Current events need web search, and the user wants a summary."}
Q: What is a good recipe for pancakes?
{"category": "off_topic", "plan": [], "reason": "Not about ultimate or flying disc sports."}"""


@dataclass
class Plan:
    category: Category
    plan: list[WorkerName]
    reason: str
    source: Literal["llm", "fallback"] = "llm"


@dataclass
class Decision:
    next_node: str
    reason: str
    plan: list[WorkerName]
    cursor: int


def parse_plan(text: str) -> Plan:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON object in planner output")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid planner JSON: {exc}") from exc
    category = data.get("category")
    if category not in CATEGORIES:
        raise ValueError(f"invalid category {category!r}")
    steps: list[str] = []
    for worker in data.get("plan") or []:
        if worker in WORKERS and worker not in steps:
            steps.append(worker)
    steps = steps[:MAX_PLAN_LENGTH]
    if steps and steps[0] == "summary":
        steps = ["research", *steps][:MAX_PLAN_LENGTH]
    if category == "off_topic":
        steps = []
    elif not steps:
        steps = list(DEFAULT_PLAN[category])
    return Plan(category=category, plan=steps, reason=str(data.get("reason") or "").strip() or "no reason given")


async def make_plan(query: str, llm) -> Plan:
    try:
        reply = await llm.call("supervisor", [SystemMessage(SUPERVISOR_PROMPT), HumanMessage(query)])
        return parse_plan(reply.text)
    except (LLMUnavailableError, ValueError) as exc:
        logger.warning("Planner fell back to default plan: %s", exc)
        return Plan(category="rules", plan=["research"], source="fallback",
                    reason=f"planner unavailable ({type(exc).__name__}); defaulting to research")


def decide_next(category: Category, plan: list[WorkerName], cursor: int,
                results: list[WorkerResult]) -> Decision:
    plan = list(plan)
    if category == "off_topic":
        return Decision("finalize", "off-topic, no worker", plan, cursor)
    if len(results) >= MAX_WORKER_RUNS:
        return Decision("finalize", "step limit reached", plan, cursor)

    ran_research = any(r["worker"] == "research" for r in results)
    last = results[-1] if results else None
    carried_reason: str | None = None
    if last is not None:
        error = (last["error"] or "")[:120]
        if last["escalate"] and not ran_research:
            plan.insert(cursor, "research")
            reason = f"{last['meta'].get('reason', 'worker requested escalation')}; escalating to research for web lookup"
            return Decision("research", reason, plan, cursor + 1)
        if not last["ok"] and last["worker"] == "data" and not ran_research:
            plan.insert(cursor, "research")
            return Decision("research", f"data failed ({error}); falling back to research", plan, cursor + 1)
        if not last["ok"] and last["worker"] == "research":
            plan = plan[:cursor] + [w for w in plan[cursor:] if w != "summary"]
            carried_reason = f"research failed ({error}); skipping summary"
        if not last["ok"] and last["worker"] == "summary":
            return Decision("finalize", f"summary failed ({error}); returning previous draft", plan, cursor)

    if cursor < len(plan):
        reason = carried_reason or f"next planned worker {cursor + 1}/{len(plan)}"
        return Decision(plan[cursor], reason, plan, cursor + 1)
    return Decision("finalize", carried_reason or "plan complete", plan, cursor)
