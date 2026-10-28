from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, BaseMessage

from app.config import Settings
from app.events import token, trace
from app.llm.providers import Provider, build_chat_model, model_id


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Route:
    agent: str
    provider: Provider
    dimension: str
    reason: str


ROUTES: dict[str, Route] = {
    "supervisor": Route("supervisor", "gemini", "cost",
                        "Runs on every request and returns a short JSON plan; cheapest, lowest-latency model."),
    "research": Route("research", "openai", "capability",
                      "Must answer strictly from retrieved sources with [S#] citations; strongest instruction following."),
    "summary": Route("summary", "deepseek", "cost",
                     "Long retrieved context in, short summary out; lowest per-token price for long inputs."),
    "data": Route("data", "deepseek", "hybrid",
                  "Text-to-SQL over a small fixed schema; structured task that a low-cost model handles reliably."),
}

FALLBACK: dict[str, Provider] = {
    "supervisor": "openai",
    "research": "gemini",
    "summary": "gemini",
    "data": "gemini",
}

# Last-resort backup for every agent, tried only after the primary and its fallback both failed.
BACKUP: Provider = "kimi"
BACKUP_REASON = "last-resort backup after primary and fallback failed"

ModelFactory = Callable[[Settings, Provider], object]


class LLMUnavailableError(RuntimeError):
    pass


@dataclass
class LLMReply:
    text: str
    provider: Provider
    model: str
    fallback: bool
    elapsed_ms: int
    usage: dict[str, int] = field(default_factory=dict)


def _short_error(exc: BaseException) -> str:
    detail = str(exc).replace("\n", " ").strip()[:200]
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block if isinstance(block, str) else str(block.get("text", ""))
            for block in content
            if isinstance(block, (str, dict))
        )
    return str(content)


class _StreamStarted(Exception):
    """Raised internally when a provider fails after tokens reached the user."""


class RoutedLLM:
    """Calls the provider assigned to an agent, then its fallback, then the shared backup (if configured)."""

    def __init__(self, settings: Settings, factory: ModelFactory = build_chat_model) -> None:
        self.settings = settings
        self.factory = factory

    async def call(self, agent: str, messages: list[BaseMessage], *, stream: bool = False) -> LLMReply:
        route = ROUTES[agent]
        attempts: list[tuple[Provider, bool, str]] = [
            (route.provider, False, route.reason),
        ]
        last_error = "unknown error"
        for index, (provider, is_fallback, reason) in enumerate(attempts):
            trace("llm_route", agent, provider=provider, model=model_id(self.settings, provider),
                  dimension=route.dimension, reason=reason, fallback=is_fallback, tier=index)
            try:
                return await self._attempt(agent, provider, messages, stream, is_fallback)
            except _StreamStarted as exc:
                raise LLMUnavailableError(f"{agent}: failed mid-stream ({exc})") from exc
            except Exception as exc:  # provider SDKs raise many unrelated types
                # Provider messages can echo request details (e.g. a masked API key), so the full text
                # stays in server logs and client-visible traces/errors only get the exception type.
                logger.warning("LLM call failed for %s via %s: %s", agent, provider, _short_error(exc))
                last_error = type(exc).__name__
                if index == 0:
                    attempts.append((FALLBACK[agent], True, f"primary {provider} failed: {last_error}"))
                elif index == 1 and self.settings.kimi_api_key is not None:
                    attempts.append((BACKUP, True, f"fallback {provider} failed: {last_error}; {BACKUP_REASON}"))
        raise LLMUnavailableError(f"{agent}: all providers failed ({last_error})")

    async def _attempt(self, agent: str, provider: Provider, messages: list[BaseMessage],
                       stream: bool, is_fallback: bool) -> LLMReply:
        model = self.factory(self.settings, provider)
        started = time.perf_counter()
        usage: dict[str, int] = {}
        parts: list[str] = []
        try:
            async with asyncio.timeout(self.settings.llm_timeout_seconds):
                if stream:
                    # Usage arrives as per-chunk deltas on some providers (Gemini) and only on the
                    # last chunk on others (OpenAI); summing the chunks handles both.
                    aggregate = None
                    async for chunk in model.astream(messages):
                        aggregate = chunk if aggregate is None else aggregate + chunk
                        piece = _text(chunk.content)
                        if piece:
                            parts.append(piece)
                            token(piece, agent)
                    usage = dict(getattr(aggregate, "usage_metadata", None) or {})
                else:
                    message: AIMessage = await model.ainvoke(messages)
                    parts.append(_text(message.content))
                    usage = dict(message.usage_metadata or {})
        except Exception as exc:  # includes TimeoutError raised by asyncio.timeout
            if stream and parts:
                logger.warning("LLM stream failed for %s via %s: %s", agent, provider, _short_error(exc))
                raise _StreamStarted(type(exc).__name__) from exc
            raise
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        reply = LLMReply("".join(parts), provider, model_id(self.settings, provider), is_fallback, elapsed_ms, usage)
        trace("llm_done", agent, provider=provider, model=reply.model, elapsed_ms=elapsed_ms,
              input_tokens=usage.get("input_tokens", 0), output_tokens=usage.get("output_tokens", 0))
        return reply
