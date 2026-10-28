from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.agents.deps import AgentDeps
from app.config import Settings
from app.llm.router import LLMReply, LLMUnavailableError


class FakeLLM:
    """Returns scripted replies per agent; records every call."""

    def __init__(self, replies: dict[str, list[str]] | None = None, fail: set[str] | None = None):
        self.replies = {k: list(v) for k, v in (replies or {}).items()}
        self.fail = fail or set()
        self.calls: list[dict] = []

    async def call(self, agent, messages, *, stream=False):
        self.calls.append({"agent": agent, "messages": messages, "stream": stream})
        if agent in self.fail:
            raise LLMUnavailableError(f"{agent}: all providers failed (test)")
        text = self.replies.get(agent, ["ok"]).pop(0) if self.replies.get(agent) else "ok"
        return LLMReply(text=text, provider="openai", model="fake", fallback=False, elapsed_ms=1, usage={})


class FakeStore:
    def __init__(self, chunks: list[dict] | None = None, fail: bool = False):
        self.chunks, self.fail = chunks or [], fail

    def search(self, query: str, k: int) -> list[dict]:
        if self.fail:
            raise RuntimeError("chroma broken")
        return self.chunks[:k]


@dataclass
class FakeTavily:
    available: bool = True
    search_results: list[dict] = field(default_factory=list)
    extract_results: list[dict] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)

    async def search(self, query: str, agent: str, max_results: int = 5) -> list[dict]:
        self.calls.append(("search", agent))
        return self.search_results if self.available else []

    async def extract(self, urls: list[str], agent: str) -> list[dict]:
        self.calls.append(("extract", agent))
        return self.extract_results if self.available else []


def chunk(cid: str, score: float, text: str = "The stall count is ten seconds.") -> dict:
    doc_id = cid.split(":")[0]
    return {"chunk_id": cid, "doc_id": doc_id, "title": doc_id, "page": 1, "text": text,
            "source_url": f"https://example.org/{doc_id}.pdf", "score": score}


def make_deps(llm=None, store=None, tavily=None, medals_db: Path | None = None, **settings) -> AgentDeps:
    return AgentDeps(settings=Settings(_env_file=None, **settings), llm=llm or FakeLLM(),
                     store=store, tavily=tavily or FakeTavily(), medals_db=medals_db or Path("missing.sqlite"))
