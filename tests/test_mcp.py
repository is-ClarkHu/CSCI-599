from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.mcp_client import build_connections, discover_mcp_tools


@pytest.mark.asyncio
@pytest.mark.integration
async def test_all_three_servers_perform_real_tool_discovery(tmp_path: Path) -> None:
    settings = Settings(
        openai_api_key="test-only",
        mcp_files_root=tmp_path,
        mcp_discovery_timeout_seconds=15,
    )

    discovery = await discover_mcp_tools(build_connections(settings), 15)

    assert set(discovery.states) == {"filesystem", "tavily", "weather"}
    assert all(state.connected for state in discovery.states.values())
    assert any(name.startswith("filesystem_") for name in discovery.states["filesystem"].tools)
    assert any(name.startswith("tavily_") for name in discovery.states["tavily"].tools)
    assert discovery.states["weather"].tools == ["weather_get_weather"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_filesystem_tools_call_over_mcp(tmp_path: Path) -> None:
    settings = Settings(openai_api_key="test-only", mcp_files_root=tmp_path)
    connection = {"filesystem": build_connections(settings)["filesystem"]}
    discovery = await discover_mcp_tools(connection, 15)
    tools = {tool.name: tool for tool in discovery.tools}

    await tools["filesystem_write_file"].ainvoke(
        {"path": str(tmp_path / "proof.txt"), "content": "real MCP call"}
    )
    content = await tools["filesystem_read_text_file"].ainvoke(
        {"path": str(tmp_path / "proof.txt")}
    )

    assert "real MCP call" in str(content)


@pytest.mark.asyncio
async def test_unavailable_server_does_not_hide_healthy_server(tmp_path: Path) -> None:
    settings = Settings(openai_api_key="test-only", mcp_files_root=tmp_path)
    connections = {
        "broken": {
            "transport": "stdio",
            "command": str(tmp_path / "does-not-exist"),
            "args": [],
        },
        "weather": build_connections(settings)["weather"],
    }

    discovery = await discover_mcp_tools(connections, 5)

    assert discovery.states["broken"].connected is False
    assert discovery.states["broken"].error
    assert discovery.states["weather"].connected is True
    assert "weather_get_weather" in {tool.name for tool in discovery.tools}
