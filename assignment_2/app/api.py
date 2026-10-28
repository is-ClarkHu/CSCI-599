from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from app.config import PROJECT_ROOT, Settings
from app.events import sse_frame
from app.llm.providers import model_id
from app.llm.router import BACKUP, FALLBACK, ROUTES
from app.service import AssistantService


logger = logging.getLogger(__name__)
STATIC_DIR = PROJECT_ROOT / "static"


class ChatRequest(BaseModel):
    query: str = Field(max_length=2000)
    session_id: str | None = Field(default=None, max_length=100)

    @field_validator("query")
    @classmethod
    def strip_and_require(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be empty")
        return value


def create_app(settings: Settings | None = None,
               service_factory: Callable[[Settings], AssistantService] = AssistantService) -> FastAPI:
    resolved = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        service = service_factory(resolved)
        app.state.service = service
        await service.initialize()
        yield

    app = FastAPI(title="Ultimate Frisbee Multi-Agent Assistant", version="1.0.0", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    async def health(request: Request) -> dict:
        service = request.app.state.service
        routing = [{"agent": r.agent, "provider": r.provider, "model": model_id(resolved, r.provider),
                    "dimension": r.dimension, "reason": r.reason, "fallback": FALLBACK[r.agent],
                    "backup": BACKUP if resolved.kimi_api_key is not None else None}
                   for r in ROUTES.values()]
        return {"status": "ok" if service.healthy else "degraded", "can_serve": service.can_serve,
                "components": service.components, "routing": routing}

    @app.post("/api/chat")
    async def chat(payload: ChatRequest, request: Request) -> StreamingResponse:
        service = request.app.state.service
        if not service.can_serve:
            raise HTTPException(status_code=503, detail="Service is not ready; see /health")
        logger.info("chat session=%s chars=%d", payload.session_id, len(payload.query))

        async def frames() -> AsyncIterator[str]:
            async for event, data in service.stream(payload.query):
                yield sse_frame(event, data)

        return StreamingResponse(frames(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app
