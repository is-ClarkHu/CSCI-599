from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.agent import AgentUnavailableError
from app.api import create_app
from app.config import Settings


@dataclass
class FakeService:
    settings: Settings
    ready: bool = True
    discovery = None
    initialization_error = None

    async def initialize(self) -> None:
        return None

    async def chat(self, query: str, session_id: str) -> str:
        return f"{session_id}: {query}"


class UnavailableService(FakeService):
    ready = False
    initialization_error = "test initialization failure"

    async def chat(self, query: str, session_id: str) -> str:
        raise AgentUnavailableError(self.initialization_error)


def test_chat_contract_and_health() -> None:
    app = create_app(Settings(), service_factory=FakeService)
    with TestClient(app) as client:
        health = client.get("/health")
        response = client.post(
            "/chat", json={"query": "hello", "session_id": "session-1"}
        )

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert response.status_code == 200
    assert response.json() == {"response": "session-1: hello"}


def test_chat_rejects_bad_input() -> None:
    app = create_app(Settings(), service_factory=FakeService)
    with TestClient(app) as client:
        empty_query = client.post(
            "/chat", json={"query": "  ", "session_id": "session-1"}
        )
        unsafe_session = client.post(
            "/chat", json={"query": "hello", "session_id": "contains spaces"}
        )
        extra_field = client.post(
            "/chat",
            json={"query": "hello", "session_id": "session-1", "extra": True},
        )

    assert empty_query.status_code == 422
    assert unsafe_session.status_code == 422
    assert extra_field.status_code == 422


def test_chat_returns_503_when_agent_is_unavailable() -> None:
    app = create_app(Settings(), service_factory=UnavailableService)
    with TestClient(app) as client:
        response = client.post(
            "/chat", json={"query": "hello", "session_id": "session-1"}
        )

    assert response.status_code == 503
    assert "initialization failure" in response.json()["detail"]
