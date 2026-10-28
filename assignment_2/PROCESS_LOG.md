# PROCESS_LOG — Assignment 2

## AI tools used

ChatGPT (chat) for product discussion and plan review; Claude Code (Claude Opus 5.5) to write the 20-task plan,
the code, tests and deployment; Codex for independent testing and git chores; Gemini to explain concepts I did
not know. At runtime the assistant calls GPT-6 Sol, Gemini 3.8 Flash and DeepSeek Flash, with Moonshot Kimi K3
as a last-resort backup.

## Development narrative

I play for the USC ultimate team and in club ultimate; new players rarely know the rules, and the rules keep
changing. I acted as product manager with ChatGPT, then had Claude write a full plan before any code. What
worked: test-first tasks and fallbacks. Where I got stuck: Gemini ran out of credit mid-project (so I added Kimi
as a backup), ragas was incompatible with langchain 1.x, and each Cloud Run redeploy took about ten minutes.

## Verification narrative

Beyond 131 unit tests and real-API integration tests, re-checked independently with Codex, a smoke test
exercises six question types on the live service after every deploy. I clicked every example question, compared
the answers with what I know as a player, read the traces, opened citations to check the PDF pages, and broke
two API keys on purpose to watch the failover reach Kimi.

## What I learned

AI could not supply what only I had: knowing which rules matter to players, judging whether an answer was right,
curating the medal table and writing the reference answers, and handling billing and keys. It also did not catch
the Tavily key leaking into logs on its own; an automated security review did. Planning first, and measuring
instead of assuming (Gemini was cheaper, not faster), worked far better than prompting ad hoc.

## Appendix: prompt → code → verification loops

Prompts are paraphrased; I did not keep the exact wording.

### Loop 1: frontend

- **Prompt:** build the Task 16 chat page: vanilla HTML/CSS/JS, SSE parsed with fetch + ReadableStream, a routing
  card, a trace panel with coloured badges, a citation panel with clickable `[S#]` links, `textContent` only.
- **Generated:** `static/index.html`, `static/app.js`, `static/style.css`.
- **Verification:** `tests/test_static.py`, the smoke test, and clicking through the deployed page.
- **Changed:** the browser check found that the routing card dropped the Supervisor's FALLBACK row, because
  rendering the later `agent_route` event cleared the card. The plan header is now prepended instead.

### Loop 2: retrieval quality

- **Prompt:** the stall-count question answered "the sources do not cover this"; find out why, measure it, and
  fix it.
- **Generated:** a hit@5 script over the 25 eval questions (baseline 15/25), then embeddings that include each
  document's title (19/25).
- **Verification:** because every similarity score rose, the web-search threshold was recalibrated (0.35 → 0.50).
  The first RAGAS run returned NaN because GPT-6 Sol rejects custom temperature; it was fixed and re-run.
- **Changed:** the stall-count question now answers "ten (10)" with a WFDF citation.
