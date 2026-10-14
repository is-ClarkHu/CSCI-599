# Process Log

## 1. AI tools used

- ChatGPT (GPT-5.6 Sol, chat interface): helped me understand the assignment PDF and compare
  framework and LLM provider options.
- OpenAI Codex (GPT-5): main coding tool. Implemented the service, wrote the tests, and
  helped debug dependency and MCP issues.
- Claude Code (Claude Opus 5.5): checked the finished project against the rubric, ran live
  multi-turn tests on the Cloud Run URL, and fixed two gaps in the README.
- Gemini Pro: answered technical questions and concepts I didn't understand, including
  parts of what the coding tools had done.
- Kimi: tried it out briefly, did not use its output in the final project.

## 2. Development narrative

I started by reading the PDF and asking ChatGPT, roughly, "What is this
assignment actually asking for? Is it just a chat service?" That made it clear the graded
part is the backend agent loop, not a UI. Hermes had come up in class, so at first I
wondered if I should build on it. After rereading the rubric I dropped that idea. The
assignment grades whether I can show memory, MCP discovery, tool calls and deployment
myself, and Hermes would hide most of that behind a bigger platform.

I picked LangGraph because it is the course-recommended stack and has a built-in
checkpointer, and the rubric does not accept a hand-written dict for memory. For the model I
talked it through with Codex and chose NVIDIA NIM: the developer key is free, Nemotron 3.5
Lightning supports tool calling, and the endpoint is OpenAI-compatible, so ChatOpenAI works
by changing the base URL. Filesystem and Tavily cover the two required servers. I added
a small Open-Meteo weather server as the third because it is a different kind of tool and
needs no API key.

Then I asked Codex to "implement Assignment 1 on the current branch using NVIDIA NIM, real
MCP calls, memory, and Cloud Run." It had the whole framework done in about 36 minutes,
which I didn't believe at first. I kept asking it what it had done and how, file by file,
before I trusted it. Testing and polishing took much longer than that.

The main problem was dependencies. The newest Python mcp package was outside the version
range langchain-mcp-adapters accepts, so I checked the dependency metadata and pinned mcp to
a compatible 1.x release. After deploying, Claude Code's rubric check caught a missing local
LLM in my deployment diagram and a missing rationale for the third server.

## 3. Verification narrative

- Ran the pytest suite (13 tests). It does real `tools/list` calls against all three MCP
  servers and a real filesystem `tools/call` that writes a file and reads it back. It also
  checks that `session_id` becomes the LangGraph `thread_id` and that two sessions don't
  share memory.
- Probed error handling on purpose: a missing server executable, a transport exception, a
  timeout, and invalid tool arguments. The service returned an explanation instead of
  crashing each time.
- Ran `npm audit` and fixed a high-severity advisory in Tavily's MCP SDK with an npm
  override.
- On the live Cloud Run URL, `/health` shows all three servers connected with 20 tools
  discovered.
- Tested the live service by hand with curl and the `/docs` page. In one session I asked a
  general knowledge question (answered with no tool), then asked for the LA weather saved to
  a file (it called weather and then filesystem), then asked "What did I ask you first?" and
  it answered correctly.

## 4. What I learned

AI could build a plausible stack very fast, but it didn't know the newest package versions
were incompatible with each other. I had to check the dependency metadata myself. A
configured MCP server also isn't proof that anything touched the wire, so I only trusted the
integration after testing tool calls directly and asking the AI to explain what it had built.
