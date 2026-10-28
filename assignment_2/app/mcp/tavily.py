from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from langchain_mcp_adapters.client import MultiServerMCPClient

from app.config import Settings
from app.events import trace


logger = logging.getLogger(__name__)

SEARCH_TOOL = "tavily_search"
EXTRACT_TOOL = "tavily_extract"
_BLOCK = re.compile(r"Title:\s*(?P<title>.+?)\s*\nURL:\s*(?P<url>\S+)\s*\n(?:Content:\s*)?(?P<content>.*?)(?=\n\s*Title:|\Z)",
                    re.DOTALL)


@dataclass
class TavilyStatus:
    connected: bool = False
    tools: list[str] = field(default_factory=list)
    error: str | None = None


def _as_text(raw: object) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        return "\n".join(_as_text(item.get("text") if isinstance(item, dict) else item) for item in raw)
    if isinstance(raw, tuple):  # some adapter versions return (content, artifact)
        return _as_text(raw[0])
    return str(raw)


def _json_results(text: str) -> list[dict] | None:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    results = data.get("results") if isinstance(data, dict) else data
    return results if isinstance(results, list) else None


def parse_search_output(raw: object) -> list[dict]:
    text = _as_text(raw).strip()
    results = _json_results(text)
    if results is not None:
        return [{"title": str(r.get("title", "")), "url": str(r["url"]), "content": str(r.get("content", ""))}
                for r in results if isinstance(r, dict) and r.get("url")]
    return [{"title": m["title"].strip(), "url": m["url"].strip(), "content": m["content"].strip()}
            for m in _BLOCK.finditer(text)]


def parse_extract_output(raw: object) -> list[dict]:
    text = _as_text(raw).strip()
    results = _json_results(text)
    if results is not None:
        return [{"url": str(r["url"]), "content": str(r.get("raw_content") or r.get("content") or "")}
                for r in results if isinstance(r, dict) and r.get("url")]
    return [{"url": item["url"], "content": item["content"]} for item in parse_search_output(text)]


class TavilyTools:
    """One shared Tavily Remote MCP connection used by every agent that needs live web data."""

    def __init__(self, settings: Settings, client_factory: Callable[..., object] = MultiServerMCPClient) -> None:
        self.settings = settings
        self.client_factory = client_factory
        self.status = TavilyStatus()
        self._tools: dict[str, object] = {}

    @property
    def available(self) -> bool:
        return self.status.connected and SEARCH_TOOL in self._tools

    async def start(self) -> TavilyStatus:
        url = self.settings.tavily_mcp_url
        if url is None:
            self.status = TavilyStatus(error="TAVILY_API_KEY is not configured")
            return self.status
        try:
            client = self.client_factory({"tavily": {"transport": "streamable_http", "url": url}},
                                         tool_name_prefix=False)
            async with asyncio.timeout(self.settings.mcp_timeout_seconds):
                tools = await client.get_tools()
            self._tools = {tool.name: tool for tool in tools}
            self.status = TavilyStatus(connected=True, tools=sorted(self._tools))
        except Exception as exc:
            self.status = TavilyStatus(error=f"{type(exc).__name__}: {str(exc)[:200]}".replace(url, "<tavily-url>"))
            logger.warning("Tavily MCP unavailable: %s", self.status.error)
        return self.status

    async def search(self, query: str, agent: str, max_results: int = 5) -> list[dict]:
        items = await self._call(SEARCH_TOOL, {"query": query, "max_results": max_results}, agent,
                                 parse_search_output)
        return items[:max_results]

    async def extract(self, urls: list[str], agent: str) -> list[dict]:
        return await self._call(EXTRACT_TOOL, {"urls": urls}, agent, parse_extract_output)

    async def _call(self, name: str, args: dict, agent: str,
                    parser: Callable[[object], list[dict]]) -> list[dict]:
        started = time.perf_counter()
        tool = self._tools.get(name)
        if tool is None:
            trace("mcp_tool_call", agent, server="tavily", tool=name, ok=False,
                  error=self.status.error or f"{name} not available", elapsed_ms=0)
            return []
        try:
            async with asyncio.timeout(self.settings.mcp_timeout_seconds):
                raw = await tool.ainvoke(args)
            items = parser(raw)
        except Exception as exc:
            trace("mcp_tool_call", agent, server="tavily", tool=name, ok=False,
                  error=type(exc).__name__, elapsed_ms=int((time.perf_counter() - started) * 1000))
            return []
        trace("mcp_tool_call", agent, server="tavily", tool=name, ok=True, results=len(items),
              args={k: v for k, v in args.items() if k != "urls"} or {"urls": len(args.get("urls", []))},
              elapsed_ms=int((time.perf_counter() - started) * 1000))
        return items
