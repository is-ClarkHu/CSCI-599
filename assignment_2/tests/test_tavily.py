from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.mcp.tavily import TavilyTools, parse_extract_output, parse_search_output


TEXT_SAMPLE = """Detailed Results:

Title: WUGC 2024 Final
URL: https://wfdf.sport/a
Content: USA beat Japan in the open final.

Title: Women's final recap
URL: https://wfdf.sport/b
Content: Colombia won gold.
"""


def test_parse_text_search_output() -> None:
    items = parse_search_output(TEXT_SAMPLE)
    assert [i["url"] for i in items] == ["https://wfdf.sport/a", "https://wfdf.sport/b"]
    assert items[0]["title"] == "WUGC 2024 Final"
    assert "USA beat Japan" in items[0]["content"]


def test_parse_json_search_output() -> None:
    raw = json.dumps({"results": [{"title": "T", "url": "https://x", "content": "C"}]})
    assert parse_search_output(raw) == [{"title": "T", "url": "https://x", "content": "C"}]


def test_parse_content_block_list() -> None:
    raw = [{"type": "text", "text": TEXT_SAMPLE}]
    assert len(parse_search_output(raw)) == 2


def test_parse_garbage_returns_empty() -> None:
    assert parse_search_output("nothing useful here") == []
    assert parse_extract_output(None) == []


def test_parse_extract_json() -> None:
    raw = json.dumps({"results": [{"url": "https://x", "raw_content": "full page"}]})
    assert parse_extract_output(raw) == [{"url": "https://x", "content": "full page"}]


class FakeTool:
    def __init__(self, name: str, output=None, fail: bool = False):
        self.name, self.output, self.fail = name, output, fail
        self.calls: list[dict] = []

    async def ainvoke(self, args: dict):
        self.calls.append(args)
        if self.fail:
            raise ConnectionError("down")
        return self.output


class FakeClient:
    def __init__(self, tools=None, fail: bool = False):
        self.tools, self.fail = tools or [], fail

    async def get_tools(self):
        if self.fail:
            raise ConnectionError("cannot reach tavily")
        return self.tools


@pytest.fixture
def traces(monkeypatch):
    seen: list[dict] = []
    monkeypatch.setattr("app.mcp.tavily.trace", lambda kind, node, **d: seen.append({"kind": kind, "node": node, **d}))
    return seen


async def test_search_records_calling_agent(traces) -> None:
    search = FakeTool("tavily_search", TEXT_SAMPLE)
    tavily = TavilyTools(Settings(_env_file=None, tavily_api_key="k"),
                         client_factory=lambda *a, **k: FakeClient([search, FakeTool("tavily_extract")]))
    status = await tavily.start()
    assert status.connected and tavily.available
    items = await tavily.search("wugc 2024", agent="research")
    assert len(items) == 2
    assert search.calls[0]["query"] == "wugc 2024"
    assert traces[-1]["kind"] == "mcp_tool_call" and traces[-1]["node"] == "research"
    assert traces[-1]["ok"] is True and traces[-1]["tool"] == "tavily_search"
    assert traces[-1]["results"] == 2


async def test_unavailable_server_degrades_without_raising(traces) -> None:
    tavily = TavilyTools(Settings(_env_file=None, tavily_api_key="k"),
                         client_factory=lambda *a, **k: FakeClient(fail=True))
    status = await tavily.start()
    assert status.connected is False and "ConnectionError" in status.error
    assert await tavily.search("x", agent="data") == []
    assert traces[-1]["ok"] is False and traces[-1]["node"] == "data"


async def test_missing_key_means_unavailable(traces) -> None:
    tavily = TavilyTools(Settings(_env_file=None))
    status = await tavily.start()
    assert status.connected is False and status.error == "TAVILY_API_KEY is not configured"


async def test_tool_failure_returns_empty(traces) -> None:
    tavily = TavilyTools(Settings(_env_file=None, tavily_api_key="k"),
                         client_factory=lambda *a, **k: FakeClient([FakeTool("tavily_search", fail=True),
                                                                   FakeTool("tavily_extract", fail=True)]))
    await tavily.start()
    assert await tavily.extract(["https://x"], agent="summary") == []
    assert traces[-1]["ok"] is False and traces[-1]["node"] == "summary"


@pytest.mark.integration
async def test_real_tavily_remote_mcp() -> None:
    tavily = TavilyTools(Settings())
    status = await tavily.start()
    assert status.connected, status.error
    assert "tavily_search" in status.tools and "tavily_extract" in status.tools
    items = await tavily.search("World Ultimate Championships", agent="research", max_results=2)
    assert items and items[0]["url"].startswith("http")
