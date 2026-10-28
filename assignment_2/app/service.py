from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator

from app.agents.deps import AgentDeps
from app.config import PROJECT_ROOT, Settings
from app.data.medals_db import schema_summary
from app.graph.builder import build_graph
from app.llm.router import RoutedLLM
from app.mcp.tavily import TavilyTools
from app.rag.store import ChunkStore


logger = logging.getLogger(__name__)


def _expected_chunk_count() -> int | None:
    path = PROJECT_ROOT / "corpus" / "index_manifest.json"
    try:
        return int(json.loads(path.read_text(encoding="utf-8"))["chunk_count"])
    except (OSError, ValueError, KeyError):
        return None


class AssistantService:
    """Owns long-lived dependencies and turns one graph run into a stream of UI events."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.timeout_seconds = settings.request_timeout_seconds
        self.graph = None
        self.components: dict[str, dict] = {}

    @property
    def providers_configured(self) -> dict[str, bool]:
        return {"openai": self.settings.openai_api_key is not None,
                "gemini": self.settings.google_api_key is not None,
                "deepseek": self.settings.deepseek_api_key is not None,
                "kimi": self.settings.kimi_api_key is not None}

    @property
    def can_serve(self) -> bool:
        return self.graph is not None and sum(self.providers_configured.values()) >= 2

    @property
    def healthy(self) -> bool:
        required = ("llm", "rag_index", "tavily_mcp", "medals_db")
        return self.can_serve and all(self.components.get(name, {}).get("ok") for name in required)

    async def initialize(self) -> None:
        self.components["llm"] = {"ok": sum(self.providers_configured.values()) >= 2,
                                  "providers": self.providers_configured}
        store = None
        try:
            if self.settings.chroma_path.exists() and self.settings.openai_api_key is not None:
                store = ChunkStore(self.settings)
                chunks = store.count()
                expected = _expected_chunk_count()
                error = None
                if chunks == 0:
                    store, error = None, "index is empty"
                elif expected is not None and chunks != expected:
                    error = f"stale index: {chunks} chunks, index_manifest expects {expected}"
                self.components["rag_index"] = {"ok": error is None, "chunks": chunks, "error": error}
            else:
                self.components["rag_index"] = {"ok": False, "chunks": 0,
                                                "error": "index directory or OPENAI_API_KEY missing"}
        except Exception as exc:
            store = None
            self.components["rag_index"] = {"ok": False, "chunks": 0, "error": type(exc).__name__}
            logger.exception("Chroma index unavailable")

        tavily = TavilyTools(self.settings)
        status = await tavily.start()
        has_tools = {"tavily_search", "tavily_extract"} <= set(status.tools)
        self.components["tavily_mcp"] = {"ok": status.connected and has_tools, "tools": status.tools,
                                         "error": status.error or (None if has_tools else "search/extract missing")}

        try:
            rows = schema_summary(self.settings.medals_db)["rows"] if self.settings.medals_db.exists() else 0
            self.components["medals_db"] = {"ok": rows > 0, "rows": rows}
        except Exception as exc:
            self.components["medals_db"] = {"ok": False, "rows": 0, "error": type(exc).__name__}

        deps = AgentDeps(settings=self.settings, llm=RoutedLLM(self.settings), store=store,
                         tavily=tavily, medals_db=self.settings.medals_db)
        self.graph = build_graph(deps)

    async def stream(self, query: str) -> AsyncIterator[tuple[str, dict]]:
        request_id = uuid.uuid4().hex[:12]
        started = time.perf_counter()
        ttft_ms: int | None = None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async for mode, item in self.graph.astream({"query": query, "results": []},
                                                           stream_mode=["custom", "values"]):
                    if mode != "custom":
                        continue
                    if item["event"] == "token" and ttft_ms is None:
                        ttft_ms = int((time.perf_counter() - started) * 1000)
                    yield item["event"], item["data"]
        except TimeoutError:
            logger.warning("Request %s timed out", request_id)
            yield "error", {"message": f"Request timed out after {int(self.timeout_seconds)} s"}
        except Exception as exc:
            logger.exception("Request %s failed", request_id)
            yield "error", {"message": f"Internal error ({type(exc).__name__})"}
        yield "done", {"elapsed_ms": int((time.perf_counter() - started) * 1000),
                       "ttft_ms": ttft_ms, "request_id": request_id}
