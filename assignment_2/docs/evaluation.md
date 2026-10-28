# Evaluation

All numbers below were produced on 2026-10-27 by the scripts in `eval/`; raw outputs are in `eval/results/`.
Latency and cost were measured against the live Cloud Run service with all three primary providers healthy
(Gemini Supervisor, OpenAI Research, DeepSeek Summary/Data) and Kimi configured as the last-resort backup. Kimi
was never needed during these runs.

## 1. RAGAS — isolated vector RAG (web search disabled)

- **Scope (Piazza #146):** only the Research agent's vector-RAG path. `eval/ragas_eval.py` runs `run_research`
  directly with `Settings(web_enabled=False)`; Tavily is never started, and the Data agent is not evaluated.
- **Test set:** `eval/questions.jsonl`, 25 fixed questions: 12 basic rules, 2 spirit, 2 annotations, 1 appendix,
  1 beach, 2 beach 4s, 2 WFDF vs USA Ultimate comparison, 1 summary of changes, 1 game advisor, 1 timings,
  1 hand signals. Each `reference` answer was written by hand from the PDF text and carries a `source`
  (document id and page).
- **Settings:** k = 5, OpenAI `text-embedding-3-small`, title-prefixed chunk embeddings.
  Judge LLM: OpenAI `gpt-6-sol` (with `bypass_temperature=True`, since the model only accepts the default temperature).
  Metrics: `Faithfulness`, `ResponseRelevancy`, `LLMContextPrecisionWithReference`, `LLMContextRecall` (ragas 0.4.3).
- **Run:** `python -m eval.ragas_eval [--research-provider openai|gemini|deepseek]`. The script refuses to write
  results unless every answer came from the requested provider with no fallback.

| Research provider | Faithfulness | Answer relevancy | Context precision | Context recall | Median s / question |
|---|---|---|---|---|---|
| OpenAI `gpt-6-sol` (production) | **0.851** | **0.590** | **0.731** | 0.480 | **2.57** |
| Gemini `gemini-3.8-flash` | 0.847 | 0.557 | 0.723 | 0.480 | 7.07 |
| DeepSeek `deepseek-flash` | 0.781 | 0.570 | 0.714 | 0.480 | 5.26 |

Context precision and context recall measure retrieval, which is identical across the three runs; the small
precision differences come from judge variance. Recall is the weakest metric. (The Gemini run used Gemini's
default thinking level; production now uses `thinking_level="low"`, see §2.)

**Error analysis**

- **q23 "What is the hand signal for a foul?"** scored 0 on all four metrics. The answer lives in
  `wfdf-hand-signals`, a 2-page PDF whose signals are mostly pictures, so text extraction yields only short
  captions (5 chunks). Nothing relevant is retrieved, and the agent correctly says "The provided sources do not
  cover this." That is faithful, but it is an empty answer. A fix would need OCR or hand-written captions for
  the figures.
- **q01 / q03 (stall count, scoring a point):** context recall 0. The WFDF definition sentences (rules p.5,
  p.8–9) lose to USA Ultimate and annotation chunks that use the same vocabulary. The answers are still correct
  (q01: "ten (10)", citing WFDF p.14), but they cite neighbouring passages rather than the reference page, and
  q03 answered from the USA Ultimate text. Title-prefixed embeddings raised strict page-level hit@5 from 15/25
  to 19/25, and q01–q03 are among the remaining misses. Next steps would be hybrid BM25 + vector retrieval, or
  restricting retrieval to the rulebook named in the question.
- **Refusals (q05, q08, q10, q20):** when the needed chunk is missing from the top 5, the model follows the
  prompt and refuses instead of guessing. That keeps faithfulness high but scores 0 on answer relevancy, which
  explains most of the gap between faithfulness (0.85) and answer relevancy (0.59).

## 2. Latency

Measured with `python -m eval.latency <url>`. Each query is sent **twice in a row and the second (Warm) request
is reported** (Piazza #171). **TTFT** is measured client-side from sending the request to the first
user-visible answer `token` event (not the first trace event). The server's own `done.ttft_ms` is stored in
`latency.json` as well.

| Category | Query (warm run) | **TTFT (s)** | Retrieval (ms) | LLM ms by provider | Web / MCP (ms) | Total (s) |
|---|---|---|---|---|---|---|
| rules | How long is the stall count under WFDF rules? | 4.69 | 237 | gemini 1724, openai 2865 | 0 | 4.96 |
| rules | What happens after a contested foul? | 3.63 | 260 | gemini 1826, openai 1505 | 0 | 3.70 |
| summary | Summarize how WFDF and USA Ultimate differ on fouls. | 11.95 | 217 | gemini 2082, openai 5291, deepseek 4803 | 0 | 12.50 |
| stats | How many WUGC open division gold medals has the United States won? | 4.81 | 0 | gemini 3104, deepseek 1646 | 0 | 4.87 |
| stats | Which country won the mixed division at the most recent WUGC? | 3.39 | 0 | gemini 1363, deepseek 1972 | 0 | 3.45 |
| news | What is the latest WFDF news this month? | 5.60 | 291 | gemini 2138, openai 1330 | 1969 | 5.86 |
| off_topic | Recommend a good laptop for programming. | 2.46 | 0 | gemini 2348 (planner only) | 0 | 2.46 |
| **Warm median** | | **4.69** | | | | **4.87** |

**Cold start:** the first request to a fresh revision (`eval/results/cold_start.json`) had **TTFT 5.98 s**, total
6.82 s, and no errors. Cloud Run starts the new revision (FastAPI lifespan: open Chroma, check SQLite, discover the
Tavily MCP tools) before shifting traffic to it, so most container start-up time is not visible to the first
request; what remains is first-call overhead such as new HTTP clients.

**Where the time goes:**

- Retrieval takes about 0.2–0.3 s.
- The Supervisor plan runs before any worker starts, so it is part of every TTFT. Gemini 3.8 Flash thinks by
  default; setting `thinking_level="low"` cut its output from 68–217 to 25–37 tokens with identical plans
  (planner benchmark: 2.28 s → 1.67 s average). Even so, calls from Cloud Run us-west1 still took 1.4–3.1 s
  (median ~1.8 s), slower than the 1.1–1.7 s measured earlier with GPT-6 Sol as planner (while Gemini was
  unavailable). The bottleneck is Gemini's response time from this region, not the amount of thinking.
- Summary questions are the slowest because Research runs without streaming and then Summary streams, so TTFT
  includes two full LLM calls after the plan.
- News adds two Tavily MCP calls (~2 s, dominated by `tavily_extract`).

The warm median of 4.69 s misses the 3 s target. The Supervisor stays on Gemini by design (cost routing: about
3× cheaper per planning call than GPT-6 Sol); moving it to OpenAI would save roughly 0.5 s per request at about
3× the planning cost. Streaming the Research draft when Summary is planned would shorten summary TTFT, but it
would show the user two answers, so it was not done.

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

Kimi `kimi-k3` is not in the price table: it is only a last-resort backup, was never called during these
measurements, and the cost script would flag any run that used a model without a price.

| Category (warm run) | Cost per query (USD) |
|---|---|
| rules | 0.0033 – 0.0051 |
| summary | 0.0086 |
| stats | 0.0009 |
| news | 0.0052 |
| off_topic | 0.0005 |
| **Median (excluding off-topic, all 12 runs)** | **0.0042** |

Planning on Gemini costs about $0.0005 per request (~555 input / ~30 output tokens). Stats questions are the
cheapest because both of their LLM calls (Gemini plan, DeepSeek SQL + answer) use the low-cost providers, while
rules and news answers go through GPT-6 Sol.

**One-off and fixed costs:** corpus embedding at ingestion is about 220k tokens (882k characters, title + text)
× $0.02/1M ≈ **$0.0044** per full rebuild. RAGAS runs: 25 research calls plus about 100 judge calls per provider.
Tavily: about 2–3 credits per news or summary question (`tavily_search` + `tavily_extract`); the free tier covers
the evaluation. Cloud Run with `--min-instances 0` costs nothing when idle; at 1 vCPU / 1 GiB, a 4 s request costs
roughly $0.0001 in compute, which is negligible next to LLM tokens.

## 4. Provider comparison

| Research provider | Faithfulness | Answer relevancy | Context precision | Context recall | Median latency (s) | Approx. research cost per question |
|---|---|---|---|---|---|---|
| OpenAI `gpt-6-sol` | 0.851 | 0.590 | 0.731 | 0.480 | 2.57 | ~$0.004 (≈1.6k in / 0.1–0.3k out) |
| Gemini `gemini-3.8-flash` | 0.847 | 0.557 | 0.723 | 0.480 | 7.07 (default thinking) | ~$0.002 |
| DeepSeek `deepseek-flash` | 0.781 | 0.570 | 0.714 | 0.480 | 5.26 | ~$0.0007 |

**Conclusion.** On the citation-grounded Research task, GPT-6 Sol and Gemini 3.8 Flash are equally faithful
(0.85), and DeepSeek is clearly lower (0.78). GPT-6 Sol has the best answer relevancy and is 2–3× faster per
question, at roughly 2× Gemini's and 5–6× DeepSeek's token cost. Faithfulness and latency of the user-facing
answer matter most for Research, so it stays on OpenAI (capability routing), and Gemini, which is almost as
faithful, is its fallback. Summary and Data stay on DeepSeek (cost routing): their inputs are already grounded
(a cited draft, or SQL rows), and the live traces show they keep `[S#]` labels correctly at the lowest price. The
Supervisor stays on Gemini for cost; §2 documents that it is not the fastest planner from Cloud Run us-west1.

## 5. End-to-end (optional)

`python -m scripts.smoke_test https://ultimate-assistant-nl5c2rxn7a-uw.a.run.app` against the deployed service
(web search enabled):

| Case | Result | Time (s) | Providers seen | Evidence |
|---|---|---|---|---|
| health | PASS | — | — | `status: ok`, rag_index 1064 chunks, Tavily tools discovered, medals_db 300 rows, 4 providers configured |
| rules | PASS | 4.5 | gemini, openai | `rag_retrieval` trace; "the marker counts to ten (10) …" |
| summary | PASS | 9.1 | gemini, openai, deepseek | `llm_route node=summary` (DeepSeek) |
| stats | PASS | 3.8 | gemini, deepseek | `sql_query` trace; "Japan has won 1 gold medal in the women's division at WUGC [S1]" |
| news | PASS | 8.3 | gemini, openai | `mcp_tool_call` (tavily_search) |
| off_topic | PASS | 1.9 | gemini | `transition reason = "off-topic, no worker"` |
| mcp_share | PASS | 10.6 | gemini, openai, deepseek | `tavily_extract ok=true` under both `research` and `summary` |

The Kimi backup tier is not exercised by the smoke test, because it only runs when two providers fail. It was
verified by running Research with invalid OpenAI and Gemini keys: the trace showed `openai (tier 0) → gemini
(tier 1) → kimi (tier 2)` and Kimi answered (`tests/test_router.py` also covers this path).
