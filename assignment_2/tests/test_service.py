from __future__ import annotations

import asyncio

from app.config import Settings
from app.service import AssistantService


class FakeGraph:
    def __init__(self, items=None, delay=0.0, explode=False):
        self.items, self.delay, self.explode = items or [], delay, explode

    async def astream(self, payload, stream_mode):
        if self.explode:
            raise RuntimeError("graph bug")
        for item in self.items:
            await asyncio.sleep(self.delay)
            yield item


def service_with(graph, **settings) -> AssistantService:
    service = AssistantService(Settings(_env_file=None, **settings))
    service.graph = graph
    return service


async def collect(service, query="q"):
    return [item async for item in service.stream(query)]


async def test_stream_forwards_custom_events_and_ends_with_done() -> None:
    graph = FakeGraph([("custom", {"event": "token", "data": {"text": "a", "node": "research"}}),
                       ("values", {"final_answer": "a"})])
    events = await collect(service_with(graph))
    assert [name for name, _ in events] == ["token", "done"]
    assert events[-1][1]["ttft_ms"] is not None


async def test_timeout_yields_error_then_done() -> None:
    graph = FakeGraph([("custom", {"event": "token", "data": {"text": "a", "node": "r"}})] * 5, delay=0.5)
    service = service_with(graph)
    service.timeout_seconds = 0.6
    events = await collect(service)
    assert [name for name, _ in events][-2:] == ["error", "done"]
    assert "timed out" in events[-2][1]["message"]


async def test_graph_exception_yields_error_then_done() -> None:
    events = await collect(service_with(FakeGraph(explode=True)))
    assert [name for name, _ in events] == ["error", "done"]
    assert "RuntimeError" in events[0][1]["message"]
    assert "graph bug" not in events[0][1]["message"]


async def test_initialize_degrades_without_index_or_keys(tmp_path) -> None:
    service = AssistantService(Settings(_env_file=None, chroma_persist_dir=tmp_path / "none",
                                        medals_db_path=tmp_path / "none.sqlite"))
    await service.initialize()
    assert service.can_serve is False and service.healthy is False
    assert service.components["rag_index"]["ok"] is False
    assert service.components["tavily_mcp"]["ok"] is False
    assert service.components["medals_db"]["ok"] is False
