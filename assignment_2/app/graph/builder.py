from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from langgraph.graph import END, START, StateGraph

from app.agents.data import run_data
from app.agents.deps import AgentDeps, WorkerInput
from app.agents.research import run_research
from app.agents.summary import run_summary
from app.events import citation, token, trace
from app.graph.state import GraphState
from app.graph.supervisor import decide_next, make_plan
from app.rag.answer import used_citations
from app.types import WorkerResult


logger = logging.getLogger(__name__)

WorkerFn = Callable[[WorkerInput, AgentDeps], Awaitable[WorkerResult]]

OFF_TOPIC_MESSAGE = ("I'm an Ultimate (flying disc) assistant, so I can only help with rules, spirit of the game, "
                     "world championship results and ultimate news. Try asking: \"How long is the stall count?\"")
FAILURE_MESSAGE = ("Sorry — the specialist agents could not complete this request right now. "
                   "The service is still running; please try again in a moment.")


def build_graph(deps: AgentDeps, workers: dict[str, WorkerFn] | None = None):
    workers = workers or {"research": run_research, "data": run_data, "summary": run_summary}

    async def supervisor(state: GraphState) -> dict:
        plan = await make_plan(state["query"], deps.llm)
        trace("agent_route", "supervisor", category=plan.category, plan=plan.plan,
              reason=plan.reason, planner=plan.source)
        return {"category": plan.category, "plan": plan.plan, "plan_reason": plan.reason, "cursor": 0}

    async def dispatch(state: GraphState) -> dict:
        results = state.get("results", [])
        if results and not results[-1]["ok"]:
            trace("worker_error", results[-1]["worker"], error=results[-1]["error"])
        decision = decide_next(state["category"], state["plan"], state["cursor"], results)
        trace("transition", "dispatch", next=decision.next_node, reason=decision.reason,
              plan=decision.plan, cursor=decision.cursor)
        return {"next_node": decision.next_node, "transition_reason": decision.reason,
                "plan": decision.plan, "cursor": decision.cursor}

    def worker_node(name: str) -> Callable[[GraphState], Awaitable[dict]]:
        async def node(state: GraphState) -> dict:
            inp = WorkerInput(query=state["query"], category=state["category"],
                              prior=list(state.get("results", [])),
                              final=state["cursor"] >= len(state["plan"]))
            try:
                result = await workers[name](inp, deps)
            except Exception as exc:
                logger.exception("Worker %s crashed", name)
                result = WorkerResult(worker=name, ok=False, output="", citations=[],
                                      error=f"{type(exc).__name__}: unexpected error",
                                      escalate=False, streamed=False, meta={})
            return {"results": [result]}
        return node

    async def finalize(state: GraphState) -> dict:
        if state.get("category") == "off_topic":
            token(OFF_TOPIC_MESSAGE, "finalize")
            return {"final_answer": OFF_TOPIC_MESSAGE, "final_citations": []}
        answer = next((r for r in reversed(state.get("results", [])) if r["ok"] and r["output"]), None)
        if answer is None:
            token(FAILURE_MESSAGE, "finalize")
            return {"final_answer": FAILURE_MESSAGE, "final_citations": []}
        if not answer["streamed"]:
            token(answer["output"], "finalize")
        cited = used_citations(answer["output"], answer["citations"])
        for item in cited:
            citation(item)
        return {"final_answer": answer["output"], "final_citations": cited}

    graph = StateGraph(GraphState)
    graph.add_node("supervisor", supervisor)
    graph.add_node("dispatch", dispatch)
    for name in ("research", "data", "summary"):
        graph.add_node(name, worker_node(name))
        graph.add_edge(name, "dispatch")
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "supervisor")
    graph.add_edge("supervisor", "dispatch")
    graph.add_conditional_edges("dispatch", lambda state: state["next_node"],
                                {"research": "research", "data": "data", "summary": "summary", "finalize": "finalize"})
    graph.add_edge("finalize", END)
    return graph.compile()
