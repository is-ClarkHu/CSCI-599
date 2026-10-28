from __future__ import annotations

import asyncio
import logging
import time

from app.agents.deps import AgentDeps, WorkerInput
from app.events import token, trace
from app.llm.router import LLMUnavailableError
from app.rag.answer import NO_CONTEXT_ANSWER, RAG_SYSTEM_PROMPT, build_answer_chain, build_context
from app.types import Chunk, WorkerResult


logger = logging.getLogger(__name__)

# Calibrated on the title-prefixed embeddings: every eval question's top chunk scores >= 0.52,
# while questions the rulebooks cannot answer mostly score 0.42-0.60.
RELEVANCE_THRESHOLD = 0.50
# Stricter cut for news answers, so loosely related rule text does not dilute web results.
NEWS_CHUNK_THRESHOLD = 0.60
RESEARCH_SYSTEM_PROMPT = RAG_SYSTEM_PROMPT


async def _retrieve(inp: WorkerInput, deps: AgentDeps) -> tuple[list[Chunk], bool]:
    if deps.store is None:
        return [], False
    try:
        return await asyncio.to_thread(deps.store.search, inp.query, deps.settings.retrieval_k), True
    except Exception:
        logger.exception("Chroma retrieval failed")
        return [], False


def _web_decision(inp: WorkerInput, chunks: list[Chunk], deps: AgentDeps) -> tuple[bool, str]:
    top = chunks[0]["score"] if chunks else 0.0
    if inp.category == "news":
        needed, reason = True, "question asks for current information"
    elif any(result["escalate"] for result in inp.prior):
        needed, reason = True, "data agent found no rows; escalated to web"
    elif top < RELEVANCE_THRESHOLD:
        needed, reason = True, f"rules corpus has no relevant chunk (top score {top:.2f})"
    else:
        return False, f"rules corpus is sufficient (top score {top:.2f})"
    if not (deps.settings.web_enabled and deps.tavily.available):
        return False, reason + "; web unavailable"
    return needed, reason


async def run_research(inp: WorkerInput, deps: AgentDeps) -> WorkerResult:
    started = time.perf_counter()
    chunks, retrieval_ok = await _retrieve(inp, deps)
    web_needed, web_reason = _web_decision(inp, chunks, deps)
    top_score = chunks[0]["score"] if chunks else 0.0
    trace("rag_retrieval", "research", ok=retrieval_ok, k=deps.settings.retrieval_k,
          chunks=[{"id": c["chunk_id"], "score": c["score"]} for c in chunks], top_score=top_score,
          elapsed_ms=int((time.perf_counter() - started) * 1000), web_needed=web_needed, web_reason=web_reason)

    if inp.category == "news":
        chunks = [c for c in chunks if c["score"] >= NEWS_CHUNK_THRESHOLD]
    web = await deps.tavily.search(inp.query, agent="research") if web_needed else []
    extracted_urls: list[str] = []
    if web:
        full = await deps.tavily.extract([web[0]["url"]], agent="research")
        if full and full[0].get("content"):
            web[0] = {**web[0], "content": full[0]["content"]}
            extracted_urls.append(web[0]["url"])
    contexts = [c["text"] for c in chunks] + [w.get("content", "") for w in web]
    meta = {"web_used": bool(web), "top_score": top_score, "contexts": contexts, "extracted_urls": extracted_urls}

    if not chunks and not web:
        if inp.final:
            token(NO_CONTEXT_ANSWER, "research")
        return WorkerResult(worker="research", ok=True, output=NO_CONTEXT_ANSWER, citations=[], error=None,
                            escalate=False, streamed=inp.final, meta={**meta, "no_context": True})

    context, citations = build_context(chunks, web)
    try:
        reply = await build_answer_chain(deps.llm, stream=inp.final).ainvoke({"context": context, "question": inp.query})
    except LLMUnavailableError as exc:
        return WorkerResult(worker="research", ok=False, output="", citations=citations, error=str(exc),
                            escalate=False, streamed=False, meta=meta)
    return WorkerResult(worker="research", ok=True, output=reply.text, citations=citations, error=None,
                        escalate=False, streamed=inp.final,
                        meta={**meta, "provider": reply.provider, "model": reply.model, "fallback": reply.fallback})
