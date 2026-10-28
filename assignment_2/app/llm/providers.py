from __future__ import annotations

from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from app.config import Settings


Provider = Literal["openai", "gemini", "deepseek", "kimi"]


def model_id(settings: Settings, provider: Provider) -> str:
    return {
        "openai": settings.openai_model,
        "gemini": settings.gemini_model,
        "deepseek": settings.deepseek_model,
        "kimi": settings.kimi_model,
    }[provider]


def build_chat_model(settings: Settings, provider: Provider) -> BaseChatModel:
    """Create a chat model; DeepSeek and Kimi use their OpenAI-compatible endpoints."""

    # GPT-6 Sol (reasoning effort != none), Gemini 3.8 Flash and Kimi K3 reject non-default
    # sampling parameters such as temperature, so only DeepSeek receives one.
    if provider == "openai":
        return ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            max_retries=1,
            stream_usage=True,
        )
    if provider == "deepseek":
        return ChatOpenAI(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            temperature=0,
            max_retries=1,
            stream_usage=True,
        )
    if provider == "kimi":
        return ChatOpenAI(
            model=settings.kimi_model,
            api_key=settings.kimi_api_key,
            base_url=settings.kimi_base_url,
            max_retries=1,
            stream_usage=True,
        )
    # Gemini 3.x thinks by default; "low" kept every supervisor plan identical on our checks while
    # cutting planner latency from ~2.3 s to ~1.7 s ("minimal" is rejected by gemini-3.8-flash).
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.google_api_key,
        max_retries=1,
        thinking_level="low",
    )
