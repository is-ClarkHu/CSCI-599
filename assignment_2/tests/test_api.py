from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings


class FakeService:
    def __init__(self, settings, can_serve=True, healthy=True, events=None):
        self.settings, self.can_serve, self.healthy = settings, can_serve, healthy
        self.components = {"rag_index": {"ok": True, "chunks": 10, "error": None}}
        self._events = events or [("trace", {"kind": "agent_route", "node": "supervisor"}),
                                  ("token", {"text": "Hi", "node": "research"}),
                                  ("citation", {"label": "S1"}),
                                  ("done", {"elapsed_ms": 5, "ttft_ms": 2, "request_id": "r"})]
        self.queries: list[str] = []

    async def initialize(self) -> None:
        pass

    async def stream(self, query):
        self.queries.append(query)
        for item in self._events:
            yield item


def frames(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((lines["event"], json.loads(lines["data"])))
    return out


@pytest.fixture
def client():
    service = {}

    def factory(settings):
        service["s"] = FakeService(settings)
        return service["s"]

    with TestClient(create_app(Settings(_env_file=None), service_factory=factory)) as c:
        c.service = service
        yield c


def test_chat_streams_sse_frames(client) -> None:
    response = client.post("/api/chat", json={"query": "  stall count?  "})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert [name for name, _ in frames(response.text)] == ["trace", "token", "citation", "done"]
    assert client.service["s"].queries == ["stall count?"]


@pytest.mark.parametrize("query", ["", "   ", "x" * 2001])
def test_invalid_queries_are_rejected(client, query) -> None:
    assert client.post("/api/chat", json={"query": query}).status_code == 422


def test_health_lists_routing_table(client) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert {row["agent"] for row in body["routing"]} == {"supervisor", "research", "summary", "data"}
    assert all(row["reason"] and row["fallback"] for row in body["routing"])
    assert "api_key" not in json.dumps(body).lower()


def test_not_ready_returns_503_and_degraded_health() -> None:
    app = create_app(Settings(_env_file=None),
                     service_factory=lambda s: FakeService(s, can_serve=False, healthy=False))
    with TestClient(app) as c:
        assert c.post("/api/chat", json={"query": "q"}).status_code == 503
        assert c.get("/health").json()["status"] == "degraded"


def test_broken_dependency_reports_degraded_but_still_serves() -> None:
    app = create_app(Settings(_env_file=None),
                     service_factory=lambda s: FakeService(s, can_serve=True, healthy=False))
    with TestClient(app) as c:
        body = c.get("/health").json()
        assert body["status"] == "degraded" and body["can_serve"] is True
        assert c.post("/api/chat", json={"query": "q"}).status_code == 200


def test_index_is_served(client) -> None:
    response = client.get("/")
    assert response.status_code == 200 and "<html" in response.text.lower()
