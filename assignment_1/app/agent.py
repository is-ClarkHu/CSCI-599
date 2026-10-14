from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from app.config import Settings
from app.mcp_client import (
    MCPDiscovery,
    build_connections,
    discover_mcp_tools,
    ensure_local_server_files_exist,
)


logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a careful general-purpose assistant with MCP tools.

Choose tools by semantic fit, not keyword matching:
- filesystem tools for reading, listing, and writing files inside the allowed workspace;
- Tavily tools for current web research and source discovery;
- weather tools for current conditions and forecasts.

Use no tool when general knowledge is sufficient. For multi-step requests, call as many
tools as needed and use each result before deciding the next step. When a tool returns an
error, explain the limitation and either correct the arguments, try an appropriate
alternative, or answer with what is safely known. Never claim a tool succeeded unless its
result confirms success. Preserve useful context from earlier messages in this session.
"""


class AgentUnavailableError(RuntimeError):
    pass


def _message_text(message: AIMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        if parts:
            return "\n".join(parts)
    return str(content)


class AgentService:
    """Owns the LangGraph agent, built-in checkpointer, and MCP client adapters."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.discovery: MCPDiscovery | None = None
        self.graph: Any | None = None
        self.initialization_error: str | None = None

    @property
    def ready(self) -> bool:
        return self.graph is not None

    async def initialize(self) -> None:
        if self.settings.openai_api_key is None:
            self.initialization_error = "OPENAI_API_KEY is not configured"
            logger.warning(self.initialization_error)
            return

        self.settings.files_root.mkdir(parents=True, exist_ok=True)
        connections = build_connections(self.settings)
        try:
            ensure_local_server_files_exist(connections)
            self.discovery = await discover_mcp_tools(
                connections, self.settings.mcp_discovery_timeout_seconds
            )
            if len(self.discovery.tools) == 0:
                raise RuntimeError("No MCP tools could be discovered")

            model = ChatOpenAI(
                model=self.settings.llm_model,
                api_key=self.settings.openai_api_key,
                base_url=self.settings.openai_base_url,
                temperature=0,
                timeout=self.settings.agent_timeout_seconds,
                max_retries=1,
            )
            self.graph = create_agent(
                model=model,
                tools=self.discovery.tools,
                system_prompt=SYSTEM_PROMPT,
                checkpointer=InMemorySaver(),
            )
            self.initialization_error = None
        except Exception as exc:
            self.initialization_error = f"{type(exc).__name__}: {exc}"
            logger.exception("Agent initialization failed")

    async def chat(self, query: str, session_id: str) -> str:
        if self.graph is None:
            raise AgentUnavailableError(
                self.initialization_error or "Agent initialization has not completed"
            )

        config = {
            "configurable": {"thread_id": session_id},
            "recursion_limit": 30,
        }
        try:
            async with asyncio.timeout(self.settings.agent_timeout_seconds):
                result = await self.graph.ainvoke(
                    {"messages": [{"role": "user", "content": query}]},
                    config=config,
                )
        except TimeoutError:
            logger.warning("Agent request timed out for session %s", session_id)
            return (
                "I could not finish within the request time limit. One of the model or "
                "MCP services may be slow; please retry or narrow the request."
            )
        except Exception as exc:
            logger.exception("Agent request failed for session %s", session_id)
            return (
                "I could not complete that request because a model or MCP operation "
                f"failed ({type(exc).__name__}). The service is still running; please "
                "retry or use a different tool path."
            )

        if not isinstance(result, dict):
            logger.error("Agent returned a malformed top-level result")
            return "I could not parse the model response. Please retry the request."

        messages = result.get("messages", [])
        if not isinstance(messages, list):
            logger.error("Agent returned a malformed messages collection")
            return "I could not parse the model response. Please retry the request."
        for message in reversed(messages):
            if isinstance(message, AIMessage) and not message.tool_calls:
                return _message_text(message)
        logger.error("Agent completed without a final assistant message")
        return "I could not parse a final model response. Please retry the request."
