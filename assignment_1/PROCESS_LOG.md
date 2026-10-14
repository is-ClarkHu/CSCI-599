# Process Log

## 1. AI tools used

- ChatGPT (model not recorded): interpreted the assignment PDF and compared framework and
  LLM-provider choices.
- OpenAI Codex (GPT-5): inspected the repository and assignment, implemented the service,
  researched current official package documentation, wrote tests, and diagnosed dependency
  and MCP integration issues.

## 2. Development narrative (200-300 words)

I started with an empty assignment branch containing only the repository README, so I first
read the full assignment PDF and converted the rubric into a checklist. My initial question
to ChatGPT was essentially, “What is this assignment doing, and is it just a chat service?”
That clarified that the graded object is the backend agent loop, not a chat UI. I then asked
Codex to “implement Assignment 1 on the current branch using NVIDIA NIM, real MCP calls,
memory, and Cloud Run.” The first design used LangGraph, FastAPI, the official filesystem
and Tavily servers, and a small student-authored Open-Meteo MCP server for the third-server
criterion.

The first dependency installation failed because the newest Python `mcp` 2.x package was
incompatible with `langchain-mcp-adapters`, which still required `mcp<2`. I checked the
published dependency metadata and pinned the newest compatible 1.x release instead. npm
then reported a high-severity OAuth advisory in Tavily's transitive MCP SDK. The application
uses stdio rather than OAuth, but I still added a safe npm override to the patched SDK and
confirmed that `npm audit` returned zero vulnerabilities. I also changed startup discovery
to isolate servers: one unavailable MCP process no longer prevents healthy tools from
loading. Finally, I added a non-root multi-stage image, input validation, a health endpoint,
request timeouts, deployment and packaging scripts, and three diagrams that match the real
implementation. The most useful AI output was the initial project skeleton; the most useful
human decision was insisting on real protocol tests rather than accepting configuration as
proof of integration.

## 3. Verification narrative

I ran 13 pytest tests, including actual `tools/list` calls against all three MCP servers and
an actual filesystem `tools/call` write/read round trip. I separately invoked the weather and
Tavily tools against their live APIs. I tested session isolation with LangGraph's real
`InMemorySaver`, verified that `session_id` becomes the graph `thread_id`, and injected a
missing executable, a transport exception, and a timeout to confirm graceful failure. I also
ran `npm audit`, Python compilation, Docker build/start checks, and an HTTP health check. The
full NIM-backed multi-turn smoke test is the final deployment check once a real key is loaded.

## 4. What I learned

AI could generate a plausible stack quickly, but it could not assume that the newest package
versions were compatible or that a configured MCP server had ever touched the wire. I had to
verify the protocol boundary, memory semantics, subprocess environment, and deployment
behavior with direct tests and inspect the failures before trusting the result.
