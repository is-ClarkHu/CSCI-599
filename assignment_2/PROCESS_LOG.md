# PROCESS_LOG — Assignment 2

## AI tools used

- **Claude Code (Claude Opus 5.5)** in the terminal: implemented the plan task by task, ran tests, ingested
  the corpus, ran RAGAS, built the Docker image and deployed to Cloud Run.
- **A separate planning session** produced `description/implementation_plan.md`: file layout, interfaces,
  test-first steps for 20 tasks, and the grading-rubric mapping. I made the product decisions in it myself
  (topic, three providers, Chroma, Tavily Remote MCP, stateless design, MCP sharing via `tavily_extract`).
- The frontend (`static/`) was generated from the prompt in `docs/frontend_vibecode_prompt.md`, extended in
  the plan (Task 16), then checked against the 10 UI requirements.

## Development narrative

I started from the Assignment 1 code style (pydantic-settings config, MCP error isolation, Dockerfile and
deploy script) and wrote the plan first, so every rubric item had a task and a test. The corpus (14 WFDF and
USA Ultimate PDFs) and the medal dataset (300 rows scraped from Wikipedia, cross-checked against each
page's medal table) were prepared before coding. Implementation followed the plan's dependency order:
config → LLM router with fallback → stream events → chunking and Chroma → RAG chain → SQLite and read-only
SQL → shared Tavily MCP → three agents → supervisor planner and state-driven dispatch → LangGraph → FastAPI
SSE → frontend → Docker and Cloud Run → RAGAS → latency and cost → docs. Most modules were written test-first
against fakes, and real-provider integration tests came afterwards.

## Verification narrative

- 120+ pytest unit tests cover routing and fallback, SSE framing, chunking, the Chroma store, SQL safety,
  Tavily parsing and degradation, each agent, every `decide_next` rule, the graph end to end with fakes, the
  API and the service.
- Integration tests (`pytest -m integration`) call the real OpenAI, DeepSeek, Gemini and Tavily endpoints.
- `scripts/smoke_test.py` runs six cases against a live server (rules, summary, stats, news, off-topic, and
  `mcp_share`, which asserts that `tavily_extract` was called by both `research` and `summary`). All passed
  locally before deployment, then again on Cloud Run.
- I read real traces by hand (e.g. the WUCC 2026 question: Data → 0 rows → escalation → web → correct
  answer) and checked that citations link to the right PDF pages.

## What I learned

- Library and provider details break plans: GPT-6 Sol rejects non-default `temperature` (it broke the RAGAS
  judge until `bypass_temperature=True`), the pinned ragas version was incompatible with langchain 1.x, and a
  Dockerfile that installs packages with `pip --user` needs `PYTHONUSERBASE` when later steps run as root.
- Measure retrieval before tuning prompts. A small hit@5 script showed that USA Ultimate chunks crowded out
  WFDF ones; prefixing the document title to each embedded chunk moved hit@5 from 15 to 19 out of 25. It also
  shifted every score up, so the web-search threshold had to be recalibrated.
- Fallback is not just a feature for the demo. The Gemini key ran out of credit mid-project and the system
  kept working, with `fallback=true` visible in every trace.

## Prompt → code → verification loops

### Loop 1: frontend

- **Prompt:** the Task 16 prompt (single-page vanilla HTML/CSS/JS; fetch + ReadableStream SSE parsing; routing
  card from `agent_route`/`llm_route`; trace panel with coloured badges and expandable JSON; citation panel;
  `[S#]` anchors; `textContent` only; responsive under 800px).
- **Generated:** `static/index.html`, `static/app.js`, `static/style.css`.
- **Verification:** `tests/test_static.py` (local assets only, all five event names and seven trace kinds
  handled, no `innerHTML`, no frameworks) plus a manual browser pass on the five example buttons.
- **Changed:** the off-topic case shows `off-topic, no worker` in the routing card as well as the trace, and
  the fallback row is highlighted with a FALLBACK tag.

### Loop 2: retrieval quality and the RAGAS run

- **Prompt:** "The live rules question returned 'sources do not cover this'; find out why, measure, fix."
- **Generated:** a hit@5 script over `eval/questions.jsonl` (baseline 15/25), then `embedding_text()` in
  `app/rag/store.py`, which embeds `title + text`, and a re-index from `chunks.jsonl`. hit@5 rose to 19/25.
- **Verification:** re-ran hit@5 and the scores showed every top-1 score had risen, so I measured the top-1
  distribution for in-domain and out-of-corpus queries and recalibrated `RELEVANCE_THRESHOLD` (0.35 → 0.50) and
  a stricter `NEWS_CHUNK_THRESHOLD` (0.60). The first RAGAS run returned NaN everywhere: the judge had sent
  `temperature=0.01` and GPT-6 Sol rejected it. Fixed with `bypass_temperature=True` and re-ran on the same
  25 questions.
- **Changed:** the stall-count question now answers "ten seconds" with a citation to WFDF p.14; RAGAS numbers
  are in `docs/evaluation.md`.

*Draft written by the coding agent; reviewed and edited by the student.*
