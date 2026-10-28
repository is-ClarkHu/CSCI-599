# Evaluation

All numbers below were produced on 2026-10-27 by the scripts in `eval/`; raw outputs are in `eval/results/`.

> **Gemini availability caveat.** During evaluation the Gemini API key returned `402 RESOURCE_EXHAUSTED`
> ("prepayment credits are depleted"). The Supervisor's primary provider is Gemini, so every live request
> fell back to OpenAI for planning (visible as `llm_route fallback=true` in every trace). This adds one failed
> round trip to every request, and Gemini could not be included in the RAGAS provider comparison. Re-running
> after topping up the key requires no code changes.

## 1. RAGAS — isolated vector RAG (web search disabled)

- **Scope (Piazza #146):** only the Research agent's vector-RAG path. `eval/ragas_eval.py` runs `run_research`
  directly with `Settings(web_enabled=False)`; Tavily is never started, and the Data agent is not evaluated.
- **Test set:** `eval/questions.jsonl`, 25 fixed questions: 12 basic rules, 2 spirit, 2 annotations, 1 appendix,
  1 beach, 2 beach 4s, 2 WFDF vs USA Ultimate comparison, 1 summary of changes, 1 game advisor, 1 timings,
  1 hand signals. Each `reference` answer was written by hand from the PDF text and carries a
  `source` (document id and page).
- **Settings:** k = 5, OpenAI `text-embedding-3-small`, title-prefixed chunk embeddings.
  Judge LLM: OpenAI `gpt-6-sol` (with `bypass_temperature=True`, since the model only accepts the default temperature).
  Metrics: `Faithfulness`, `ResponseRelevancy`, `LLMContextPrecisionWithReference`, `LLMContextRecall` (ragas 0.4.3).
- **Run:** `python -m eval.ragas_eval` (and `--research-provider deepseek`).

| Research provider | Faithfulness | Answer relevancy | Context precision | Context recall | Median s / question |
|---|---|---|---|---|---|
| OpenAI `gpt-6-sol` (production) | **0.851** | **0.590** | **0.731** | 0.480 | 2.57 |
| DeepSeek `deepseek-flash` | 0.781 | 0.570 | 0.714 | 0.480 | 5.26 |

Context precision and context recall measure retrieval, which is identical for both runs; the small precision
difference comes from judge variance. Recall is the weakest metric.

**Error analysis**

- **q23 "What is the hand signal for a foul?"** scored 0 on all four metrics. The answer lives in
  `wfdf-hand-signals`, a 2-page PDF whose signals are mostly pictures, so text extraction yields only short
  captions (5 chunks). Nothing relevant is retrieved, and the agent correctly says "The provided sources do not
  cover this." That is faithful, but it is an empty answer. A fix would need OCR or hand-written captions for
  the figures.
- **q01 / q03 (stall count, scoring a point):** context recall 0. The WFDF definition sentences (rules p.5,
  p.8–9) lose to USA Ultimate and annotation chunks that use the same vocabulary. The answers are still
  correct (q01: "ten (10)", citing WFDF p.14), but they cite neighbouring passages rather than the reference
  page, and q03 answered from the USA Ultimate text (faithfulness 0 because the judge did not find the claim
  in the contexts it was given). Title-prefixed embeddings raised strict page-level hit@5 from 15/25 to 19/25,
  and q01–q03 are among the remaining misses. Next steps would be hybrid BM25 + vector retrieval, or
  restricting retrieval to the rulebook named in the question.
- **Refusals (q05, q08, q10, q20):** when the needed chunk is missing from the top 5, the model follows the
  prompt and refuses instead of guessing. That keeps faithfulness high but scores 0 on answer relevancy,
  which explains most of the gap between faithfulness (0.85) and answer relevancy (0.59).

## 2. Latency

Measured against the live Cloud Run URL with `python -m eval.latency <url>`. Each query is sent **twice in a
row and the second (Warm) request is reported** (Piazza #171). **TTFT** is measured client-side from sending
the request to the first user-visible answer `token` event (not the first trace event). The server's own
`done.ttft_ms` is stored in `latency.json` as well.

| Category | Query (warm run) | **TTFT (s)** | Retrieval (ms) | LLM ms by provider | Web / MCP (ms) | Total (s) |
|---|---|---|---|---|---|---|
| rules | How long is the stall count under WFDF rules? | 4.69 | 292 | openai 4630 (planner + research) | 0 | 5.15 |
| rules | What happens after a contested foul? | 3.28 | 222 | openai 2830 | 0 | 3.28 |
| summary | Summarize how WFDF and USA Ultimate differ on fouls. | 9.09 | 255 | openai 5866, deepseek 3429 | 0 | 9.81 |
| stats | How many WUGC open division gold medals has the United States won? | 3.85 | 0 | openai 1618 (planner), deepseek 2052 | 0 | 3.89 |
| stats | Which country won the mixed division at the most recent WUGC? | 3.66 | 0 | openai 1485, deepseek 1990 | 0 | 3.71 |
| news | What is the latest WFDF news this month? | 6.77 | 214 | openai 3353 | 3404 | 7.21 |
| off_topic | Recommend a good laptop for programming. | 1.58 | 0 | openai 1359 (planner only) | 0 | 1.58 |
| **Warm median** | | **3.85** | | | | **3.89** |

**Cold start:** the first request to a fresh revision (`eval/results/cold_start.json`) had **TTFT 6.37 s**, total
6.86 s, and no errors. Cloud Run starts the new revision (FastAPI lifespan: open Chroma, check SQLite, discover the
Tavily MCP tools) before shifting traffic to it, so most container start-up time is not visible to the first
request. What remains is first-call overhead (new HTTP clients, Gemini 402 and then OpenAI planning).

**Where the time goes:** retrieval takes about 0.2–0.3 s. Every request also pays the failed Gemini call plus a
~1.1–1.7 s OpenAI planning call before any worker starts; with a funded Gemini key, the cheaper and faster planner
should cut warm TTFT by about 0.5–1 s. Summary questions are the slowest because Research runs without streaming
and then Summary streams, so TTFT includes two full LLM calls. News adds two Tavily MCP calls (~3.4 s,
dominated by `tavily_extract`). The warm median of 3.85 s misses the 3 s target; the planner fallback is the
main avoidable cost.

## 3. Cost per query

Token usage comes from each `llm_done` trace and is multiplied by `eval/prices.json` (prices checked on
2026-10-27 from the official pricing pages). One query embedding per retrieval is added (estimated at
4 characters per token). `cost_complete: true`: every call reported usage and every model had a price.

| Model | Input $/1M | Output $/1M | Source |
|---|---|---|---|
| OpenAI `gpt-6-sol` | 2.00 | 10.00 | developers.openai.com/api/docs/pricing |
| Gemini `gemini-3.8-flash` | 0.75 | 3.75 | ai.google.dev/gemini-api/docs/pricing (rates valid until 2026-12-31) |
| DeepSeek `deepseek-flash` | 0.30 | 1.20 | api-docs.deepseek.com/quick_start/pricing (peak rate; off-peak is half) |
| OpenAI `text-embedding-3-small` | 0.02 | — | developers.openai.com/api/docs/pricing |

| Category (warm run) | Cost per query (USD) |
|---|---|
| rules | 0.0042 – 0.0061 |
| summary | 0.0080 |
| stats | 0.0018 – 0.0019 |
| news | 0.0064 |
| off_topic | 0.0014 |
| **Median (excluding off-topic, all 12 runs)** | **0.0042** |

These costs are inflated by the Gemini outage: planning runs on GPT-6 Sol (~540 input / 30–80 output tokens,
about $0.0013–0.0019 per request) instead of Gemini 3.8 Flash (about $0.0005).

**One-off and fixed costs:** corpus embedding at ingestion is about 220k tokens (882k characters, title + text)
× $0.02/1M ≈ **$0.0044** per full rebuild. RAGAS runs: 25 research calls plus about 100 judge calls per provider.
Tavily: about 2–3 credits per news or summary question (`tavily_search` + `tavily_extract`); the free tier covers
the evaluation. Cloud Run with `--min-instances 0` costs nothing when idle; at 1 vCPU / 1 GiB, a 4 s request costs
roughly $0.0001 in compute, which is negligible next to LLM tokens.

## 4. Provider comparison

| Research provider | Faithfulness | Answer relevancy | Context precision | Context recall | Median latency (s) | Approx. research cost per question |
|---|---|---|---|---|---|---|
| OpenAI `gpt-6-sol` | 0.851 | 0.590 | 0.731 | 0.480 | 2.57 | ~$0.004 (≈1.6k in / 0.1–0.3k out) |
| DeepSeek `deepseek-flash` | 0.781 | 0.570 | 0.714 | 0.480 | 5.26 | ~$0.0007 |
| Gemini `gemini-3.8-flash` | not measured: API key out of credit (402) | | | | | |

**Conclusion.** On the citation-grounded Research task, GPT-6 Sol is more faithful (+0.07) and about twice as
fast as DeepSeek Flash, at roughly 5–6× the token cost. Faithfulness is the property the Research prompt depends
on, so Research stays on OpenAI (capability routing). Summary and Data stay on DeepSeek (cost routing): their
inputs are already grounded (a cited draft, or SQL rows), and the live traces show they keep `[S#]` labels
correctly at a fraction of the price. The Supervisor stays on Gemini by design (cost and latency); the current
traces show the OpenAI fallback doing that job, which proves the fallback path works but makes each request
more expensive and slower until the Gemini key is topped up.

## 5. End-to-end (optional)

`python -m scripts.smoke_test https://ultimate-assistant-nl5c2rxn7a-uw.a.run.app` against the deployed
service (web search enabled):

| Case | Result | Time (s) | Providers seen | Evidence |
|---|---|---|---|---|
| health | PASS | — | — | `status: ok`, rag_index 1064 chunks, Tavily tools discovered, medals_db 300 rows |
| rules | PASS | 4.0 | gemini (failed), openai | `rag_retrieval` trace; "stall count reaches ten (10) … [S1]" |
| summary | PASS | 9.0 | gemini, openai, deepseek | `llm_route node=summary` (DeepSeek) |
| stats | PASS | 4.3 | gemini, openai, deepseek | `sql_query` trace; "Japan has won 1 gold medal in the women's division at WUGC [S1]" |
| news | PASS | 6.9 | gemini, openai | `mcp_tool_call` (tavily_search) |
| off_topic | PASS | 1.7 | gemini, openai | `transition reason = "off-topic, no worker"` |
| mcp_share | PASS | 10.7 | gemini, openai, deepseek | `tavily_extract ok=true` under both `research` and `summary` |
