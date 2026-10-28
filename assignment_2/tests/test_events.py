from __future__ import annotations

import json

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.events import citation, sse_frame, token, trace


def test_calls_outside_graph_are_silent() -> None:
    trace("transition", "dispatch", reason="x")
    token("hi", "research")


def test_sse_frame_format() -> None:
    frame = sse_frame("token", {"text": "café\nworld"})
    assert frame.startswith("event: token\ndata: ")
    assert frame.endswith("\n\n")
    payload = frame.split("data: ", 1)[1].strip()
    assert json.loads(payload) == {"text": "café\nworld"}
    assert "\n" not in payload


class S(TypedDict):
    x: int


async def test_events_reach_custom_stream() -> None:
    def node(state: S) -> S:
        trace("transition", "n", reason="because")
        token("abc", "n")
        citation({"label": "S1", "kind": "rag", "ref": "d:p1:c0", "title": "T", "page": 1, "url": None, "snippet": "s"})
        return state

    graph = StateGraph(S)
    graph.add_node("n", node)
    graph.add_edge(START, "n")
    graph.add_edge("n", END)
    events = [item async for item in graph.compile().astream({"x": 1}, stream_mode="custom")]
    assert [e["event"] for e in events] == ["trace", "token", "citation"]
    assert events[0]["data"]["kind"] == "transition" and events[0]["data"]["reason"] == "because"
    assert events[1]["data"] == {"text": "abc", "node": "n"}
