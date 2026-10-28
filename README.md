# CSCI 599 Assignments

Coursework projects for CSCI 599, organized as independent applications with their own
dependencies, tests, deployment scripts, and documentation.

## Projects

| Project | System | Highlights | Documentation |
|---|---|---|---|
| Assignment 1 | Tool-using conversational agent | FastAPI, LangGraph, NVIDIA NIM, three MCP servers, per-session in-memory state, Cloud Run | [Assignment 1 README](assignment_1/README.md) |
| Assignment 2 | Multi-agent RAG assistant for Ultimate | LangGraph Supervisor, three specialist agents, OpenAI/Gemini/DeepSeek routing, Chroma RAG, Tavily Remote MCP, SQLite, SSE chat UI, Cloud Run | [Assignment 2 README](assignment_2/README.md) |

Assignment 2 is available as a [live Cloud Run application](https://ultimate-assistant-nl5c2rxn7a-uw.a.run.app).
Its UI exposes the agent plan, provider-routing rationale, orchestration trace, streaming
answer, and source citations for each turn.

## Repository layout

```text
.
├── assignment_1/   # Single-agent MCP tool loop
├── assignment_2/   # Multi-agent orchestration, RAG, evaluation, and frontend
├── LICENSE
└── README.md
```

Each assignment directory is self-contained and includes:

- application source and configuration;
- unit and integration tests;
- a multi-stage, non-root Dockerfile;
- Cloud Run deployment automation;
- a secret-safe submission packaging script;
- assignment-specific architecture and verification documentation.

## Development

Run commands from the assignment being worked on because the projects intentionally use
different Python and service dependencies.

```bash
cd assignment_1  # or assignment_2
cp .env.example .env
```

Then follow that assignment's README for its Python version, provider keys, local setup,
tests, packaging, and deployment steps.

Common verification commands are:

```bash
.venv/bin/pytest
.venv/bin/python -m scripts.smoke_test http://localhost:8080
```

Assignment 1 uses `python scripts/smoke_test.py` instead of module execution and also
requires its pinned npm dependencies for the local MCP servers.

## Repository hygiene

Credentials belong only in per-assignment `.env` files, which are ignored by Git. The
repository tracks `.env.example` templates, source code, tests, reproducible datasets, and
evaluation outputs while excluding local virtual environments, caches, generated archives,
raw download caches, and instructor-provided PDFs.

See the individual assignment READMEs for provider requirements, cost disclosures, known
limitations, and current deployment details.
