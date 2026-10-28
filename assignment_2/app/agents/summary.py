from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.deps import AgentDeps, WorkerInput
from app.events import trace
from app.llm.router import LLMUnavailableError
from app.types import WorkerResult


SUMMARY_SYSTEM_PROMPT = """You are the Summary agent of an Ultimate (flying disc) assistant. You receive a draft
answer and its numbered sources. Rewrite it as a concise summary for a player:
- at most 5 bullet points, at most 150 words in total;
- keep every factual claim tied to its original [S#] label, exactly as written;
- do not add facts that are not in the draft or the sources;
- if sources disagree (e.g. WFDF vs USA Ultimate), keep both and label them.
Answer in the same language as the question."""

MAX_EXTRACT_URLS = 2
EXTRACT_LIMIT = 3000


def _failed(error: str) -> WorkerResult:
    return WorkerResult(worker="summary", ok=False, output="", citations=[], error=error,
                        escalate=False, streamed=False, meta={})


async def run_summary(inp: WorkerInput, deps: AgentDeps) -> WorkerResult:
    source = next((r for r in reversed(inp.prior) if r["ok"] and r["output"]), None)
    if source is None:
        return _failed("nothing to summarize")

    citations = source["citations"]
    urls = [c["url"] for c in citations if c["kind"] == "web" and c["url"]][:MAX_EXTRACT_URLS]
    extracted: dict[str, str] = {}
    if urls and deps.settings.web_enabled and deps.tavily.available:
        for item in await deps.tavily.extract(urls, agent="summary"):
            extracted[item["url"]] = item["content"][:EXTRACT_LIMIT]

    trace("transition", "summary",
          reason=f"summarizing output of {source['worker']} with {len(citations)} sources",
          source_worker=source["worker"], source_labels=[c["label"] for c in citations],
          draft_chars=len(source["output"]), extracted_urls=list(extracted))
    sources = "\n".join(
        f"[{c['label']}] {c['title']}\n{extracted.get(c['url'] or '', c['snippet'])}" for c in citations
    )
    messages = [SystemMessage(SUMMARY_SYSTEM_PROMPT),
                HumanMessage(f"Question: {inp.query}\n\nDraft answer:\n{source['output']}\n\nSources:\n{sources}")]
    try:
        reply = await deps.llm.call("summary", messages, stream=inp.final)
    except LLMUnavailableError as exc:
        return _failed(str(exc))
    return WorkerResult(worker="summary", ok=True, output=reply.text, citations=citations, error=None,
                        escalate=False, streamed=inp.final,
                        meta={"source_worker": source["worker"], "extracted_urls": list(extracted),
                              "provider": reply.provider, "model": reply.model, "fallback": reply.fallback})
