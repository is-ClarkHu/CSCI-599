from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from app.agent import AgentService, AgentUnavailableError
from app.config import Settings
from app.schemas import ChatRequest, ChatResponse, HealthResponse, ServerStatus


logger = logging.getLogger(__name__)
ServiceFactory = Callable[[Settings], AgentService]


def create_app(
    settings: Settings | None = None,
    service_factory: ServiceFactory = AgentService,
) -> FastAPI:
    resolved_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        service = service_factory(resolved_settings)
        app.state.agent_service = service
        await service.initialize()
        yield

    app = FastAPI(
        title="CSCI 599 MCP Agent",
        version="1.0.0",
        description="A tool-using LangGraph agent backed by NVIDIA NIM.",
        lifespan=lifespan,
    )

    @app.get("/health", response_model=HealthResponse)
    async def health(request: Request) -> HealthResponse:
        service: AgentService = request.app.state.agent_service
        states = service.discovery.states if service.discovery else {}
        servers = {
            name: ServerStatus(
                connected=state.connected,
                tools=state.tools,
                error=state.error,
            )
            for name, state in states.items()
        }
        if service.initialization_error and not servers:
            servers["initialization"] = ServerStatus(
                connected=False, error=service.initialization_error
            )
        return HealthResponse(
            status="ok" if service.ready else "degraded",
            model=resolved_settings.llm_model,
            servers=servers,
        )

    @app.post("/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
        service: AgentService = request.app.state.agent_service
        try:
            response = await service.chat(payload.query, payload.session_id)
        except AgentUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return ChatResponse(response=response)

    return app
