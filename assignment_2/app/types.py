from typing import Any, Literal, TypedDict

Category = Literal["rules", "stats", "news", "off_topic"]
WorkerName = Literal["research", "data", "summary"]


class Chunk(TypedDict):
    chunk_id: str        # f"{doc_id}:p{page}:c{index}", e.g. "wfdf-rules-2025:p12:c0"
    doc_id: str          # id from corpus/manifest.json
    title: str           # document title
    page: int            # 1-based PDF page number
    text: str
    source_url: str
    score: float         # similarity (1 - cosine distance); 0.0 before indexing


class Citation(TypedDict):
    label: str           # "S1", "S2", ... written as [S1] in answers
    kind: Literal["rag", "web", "sql"]
    ref: str             # rag: chunk_id; web: URL; sql: "medals.sqlite"
    title: str
    page: int | None
    url: str | None
    snippet: str         # <= 300 characters


class WorkerResult(TypedDict):
    worker: WorkerName
    ok: bool
    output: str          # text produced by the worker (answer or intermediate result)
    citations: list[Citation]
    error: str | None
    escalate: bool       # True = worker asks for a web lookup (only data sets it)
    streamed: bool       # True = output was already streamed to the user as tokens
    meta: dict[str, Any]
