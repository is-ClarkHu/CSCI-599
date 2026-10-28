from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.llm.router import RoutedLLM
from app.mcp.tavily import TavilyTools
from app.rag.store import ChunkStore
from app.types import Category, WorkerResult


@dataclass
class AgentDeps:
    settings: Settings
    llm: RoutedLLM
    store: ChunkStore | None
    tavily: TavilyTools
    medals_db: Path


@dataclass
class WorkerInput:
    query: str
    category: Category
    prior: list[WorkerResult]
    final: bool
