from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.config import PROJECT_ROOT, Settings, child_process_environment


logger = logging.getLogger(__name__)


@dataclass
class MCPServerState:
    connected: bool = False
    tools: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class MCPDiscovery:
    tools: list[BaseTool]
    states: dict[str, MCPServerState]
    clients: list[MultiServerMCPClient]


def build_connections(settings: Settings) -> dict[str, dict[str, Any]]:
    """Return the three real stdio MCP server manifests used by the agent."""

    filesystem_entry = (
        settings.node_modules
        / "@modelcontextprotocol"
        / "server-filesystem"
        / "dist"
        / "index.js"
    )
    tavily_entry = settings.node_modules / "tavily-mcp" / "build" / "index.js"
    weather_entry = PROJECT_ROOT / "mcp_servers" / "weather_server.py"

    tavily_key = (
        settings.tavily_api_key.get_secret_value()
        if settings.tavily_api_key is not None
        else None
    )

    return {
        "filesystem": {
            "transport": "stdio",
            "command": "node",
            "args": [str(filesystem_entry), str(settings.files_root)],
            "env": child_process_environment(),
        },
        "tavily": {
            "transport": "stdio",
            "command": "node",
            "args": [str(tavily_entry)],
            "env": child_process_environment(TAVILY_API_KEY=tavily_key),
        },
        "weather": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(weather_entry)],
            "env": child_process_environment(),
        },
    }


def _safe_error(exc: BaseException) -> str:
    """Return a useful error category without leaking environment values or secrets."""

    detail = str(exc).replace("\n", " ").strip()
    if len(detail) > 240:
        detail = detail[:237] + "..."
    return f"{type(exc).__name__}: {detail or 'no detail'}"


async def discover_mcp_tools(
    connections: dict[str, dict[str, Any]], timeout_seconds: float
) -> MCPDiscovery:
    """Perform tools/list separately so one unavailable server cannot crash startup."""

    tools: list[BaseTool] = []
    states: dict[str, MCPServerState] = {}
    clients: list[MultiServerMCPClient] = []

    for server_name, connection in connections.items():
        client = MultiServerMCPClient(
            {server_name: connection},
            tool_name_prefix=True,
            handle_tool_errors=True,
        )
        clients.append(client)
        try:
            async with asyncio.timeout(timeout_seconds):
                server_tools = await client.get_tools()
            names = [tool.name for tool in server_tools]
            tools.extend(server_tools)
            states[server_name] = MCPServerState(connected=True, tools=names)
            logger.info("Discovered MCP tools from %s: %s", server_name, names)
        except (Exception, asyncio.CancelledError) as exc:
            if isinstance(exc, asyncio.CancelledError):
                raise
            error = _safe_error(exc)
            states[server_name] = MCPServerState(error=error)
            logger.warning("MCP server %s unavailable during discovery: %s", server_name, error)

    return MCPDiscovery(tools=tools, states=states, clients=clients)


def ensure_local_server_files_exist(connections: dict[str, dict[str, Any]]) -> None:
    """Fail with a focused message when npm/Python server files were not installed."""

    missing: list[Path] = []
    for connection in connections.values():
        args = connection.get("args", [])
        if not args:
            continue
        candidate = Path(args[0])
        if candidate.is_absolute() and not candidate.exists():
            missing.append(candidate)
    if missing:
        paths = ", ".join(str(path) for path in missing)
        raise RuntimeError(
            f"MCP server files are missing: {paths}. Run `npm ci` and install Python dependencies."
        )
