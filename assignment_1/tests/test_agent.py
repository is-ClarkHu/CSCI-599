from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph

from app.agent import AgentService
from app.config import Settings


class RecordingGraph:
    def __init__(self) -> None:
        self.config = None

    async def ainvoke(self, payload, config):
        self.config = config
        return {"messages": [AIMessage(content="done")]}


class FailingGraph:
    async def ainvoke(self, payload, config):
        raise ConnectionError("MCP transport closed")


class SlowGraph:
    async def ainvoke(self, payload, config):
        await asyncio.sleep(0.05)
        return {"messages": [AIMessage(content="late")]}


class MalformedGraph:
    async def ainvoke(self, payload, config):
        return {"messages": "not-a-message-list"}


@pytest.mark.asyncio
async def test_service_maps_session_id_to_langgraph_thread_id() -> None:
    service = AgentService(Settings(agent_timeout_seconds=5))
    graph = RecordingGraph()
    service.graph = graph

    response = await service.chat("hello", "thread-42")

    assert response == "done"
    assert graph.config["configurable"]["thread_id"] == "thread-42"


@pytest.mark.asyncio
async def test_transport_failure_becomes_a_stable_response() -> None:
    service = AgentService(Settings(agent_timeout_seconds=5))
    service.graph = FailingGraph()

    response = await service.chat("use a broken tool", "thread-1")

    assert "service is still running" in response
    assert "ConnectionError" in response


@pytest.mark.asyncio
async def test_timeout_becomes_a_stable_response() -> None:
    service = AgentService(Settings(agent_timeout_seconds=5))
    service.settings.agent_timeout_seconds = 0.01
    service.graph = SlowGraph()

    response = await service.chat("slow request", "thread-1")

    assert "time limit" in response


@pytest.mark.asyncio
async def test_malformed_model_response_becomes_a_stable_response() -> None:
    service = AgentService(Settings(agent_timeout_seconds=5))
    service.graph = MalformedGraph()

    response = await service.chat("trigger malformed response", "thread-1")

    assert "could not parse" in response


def test_framework_checkpointer_persists_and_isolates_sessions() -> None:
    def summarize(state: MessagesState):
        human_text = [m.content for m in state["messages"] if isinstance(m, HumanMessage)]
        return {"messages": [AIMessage(content=" | ".join(human_text))]}

    builder = StateGraph(MessagesState)
    builder.add_node("summarize", summarize)
    builder.add_edge(START, "summarize")
    builder.add_edge("summarize", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    session_a = {"configurable": {"thread_id": "session-a"}}
    session_b = {"configurable": {"thread_id": "session-b"}}
    graph.invoke({"messages": [HumanMessage(content="first turn")]}, session_a)
    second = graph.invoke(
        {"messages": [HumanMessage(content="what did I say?")]}, session_a
    )
    isolated = graph.invoke({"messages": [HumanMessage(content="new session")]}, session_b)

    assert second["messages"][-1].content == "first turn | what did I say?"
    assert isolated["messages"][-1].content == "new session"
