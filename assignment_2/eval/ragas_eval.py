"""RAGAS evaluation of the isolated vector-RAG path (web search disabled).

Usage: python -m eval.ragas_eval [--research-provider openai|gemini|deepseek]
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import statistics
import sys
import time
import types
from pathlib import Path

# ragas 0.4.3 still imports ChatVertexAI from a module that langchain-community 0.4 removed;
# it is only used in an isinstance() tuple, so an empty placeholder class is enough.
_vertex = types.ModuleType("langchain_community.chat_models.vertexai")
_vertex.ChatVertexAI = type("ChatVertexAI", (), {})
sys.modules.setdefault("langchain_community.chat_models.vertexai", _vertex)

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from ragas import EvaluationDataset, SingleTurnSample, evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import Faithfulness, LLMContextPrecisionWithReference, LLMContextRecall, ResponseRelevancy

from app.agents.deps import AgentDeps, WorkerInput
from app.agents.research import run_research
from app.config import Settings
from app.llm import router
from app.llm.providers import model_id
from app.llm.router import RoutedLLM
from app.mcp.tavily import TavilyTools
from app.rag.store import ChunkStore


ROOT = Path(__file__).resolve().parents[1]


async def collect(settings: Settings) -> list[dict]:
    deps = AgentDeps(settings=settings, llm=RoutedLLM(settings), store=ChunkStore(settings),
                     tavily=TavilyTools(settings), medals_db=settings.medals_db)  # tavily never started
    rows = []
    for line in (ROOT / "eval" / "questions.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        started = time.perf_counter()
        result = await run_research(WorkerInput(query=item["question"], category="rules", prior=[], final=False), deps)
        rows.append({**item, "response": result["output"], "contexts": result["meta"]["contexts"],
                     "ok": result["ok"], "provider": result["meta"].get("provider"),
                     "fallback": result["meta"].get("fallback"),
                     "seconds": round(time.perf_counter() - started, 2)})
        print(f"{item['id']} ok={result['ok']} {rows[-1]['seconds']}s")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--research-provider", choices=["openai", "gemini", "deepseek"], default=None)
    args = parser.parse_args()

    settings = Settings(web_enabled=False)
    provider = args.research_provider or router.ROUTES["research"].provider
    router.ROUTES["research"] = dataclasses.replace(router.ROUTES["research"], provider=provider)

    rows = asyncio.run(collect(settings))
    bad = [r["id"] for r in rows if r["fallback"] or not r["ok"] or r["provider"] != provider]
    if bad:
        # A provider comparison is only valid if every answer really came from that provider.
        raise SystemExit(f"Not all answers came from {provider} without fallback: {bad}. Fix and re-run.")
    dataset = EvaluationDataset(samples=[
        SingleTurnSample(user_input=r["question"], retrieved_contexts=r["contexts"] or [""],
                         response=r["response"], reference=r["reference"]) for r in rows
    ])
    # GPT-6 Sol only accepts the default temperature, so ragas must not override it.
    judge = LangchainLLMWrapper(ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key),
                                bypass_temperature=True)
    embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(model=settings.openai_embedding_model,
                                                             api_key=settings.openai_api_key))
    scores = evaluate(dataset, metrics=[Faithfulness(), ResponseRelevancy(), LLMContextPrecisionWithReference(),
                                        LLMContextRecall()], llm=judge, embeddings=embeddings)
    table = scores.to_pandas()
    metric_columns = [c for c in table.columns if c not in {"user_input", "retrieved_contexts", "response", "reference"}]
    summary = {c: round(float(table[c].mean()), 4) for c in metric_columns}
    out = {"provider": provider, "model": model_id(settings, provider),
           "k": settings.retrieval_k, "questions": len(rows), "summary": summary,
           "median_seconds": statistics.median(r["seconds"] for r in rows),
           "fallbacks": 0,
           "per_question": [{**r, **{c: table.iloc[i][c] for c in metric_columns}} for i, r in enumerate(rows)]}
    path = ROOT / "eval" / "results" / f"ragas_{provider}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
