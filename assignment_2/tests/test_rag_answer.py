from __future__ import annotations

from app.rag.answer import build_context, build_messages, used_citations


CHUNKS = [
    {"chunk_id": "wfdf-rules-2025:p12:c0", "doc_id": "wfdf-rules-2025", "title": "WFDF Rules", "page": 12,
     "text": "The marker may initiate a stall count.", "source_url": "https://w/r.pdf", "score": 0.8},
    {"chunk_id": "usau-rules-2026-2027:p5:c1", "doc_id": "usau-rules-2026-2027", "title": "USAU Rules", "page": 5,
     "text": "Stall count is ten seconds.", "source_url": "https://u/r.pdf", "score": 0.7},
]


def test_context_numbers_rag_then_web() -> None:
    context, citations = build_context(CHUNKS, web=[{"title": "News", "url": "https://n", "content": "x" * 5000}])
    assert [c["label"] for c in citations] == ["S1", "S2", "S3"]
    assert citations[0]["kind"] == "rag" and citations[0]["ref"] == "wfdf-rules-2025:p12:c0"
    assert citations[0]["page"] == 12 and citations[0]["url"] == "https://w/r.pdf"
    assert citations[2]["kind"] == "web" and citations[2]["url"] == "https://n"
    assert "[S1] WFDF Rules, p.12 (wfdf-rules-2025:p12:c0)" in context
    assert len(context) < 5000
    assert all(len(c["snippet"]) <= 300 for c in citations)


def test_messages_contain_question_and_context() -> None:
    messages = build_messages("What is a stall?", "[S1] ...")
    assert "Answer ONLY from the numbered sources" in messages[0].content
    assert "What is a stall?" in messages[-1].content and "[S1] ..." in messages[-1].content


def test_used_citations_keeps_only_cited_in_order() -> None:
    _, citations = build_context(CHUNKS)
    answer = "Ten seconds [S2]. The marker counts [S1][S2]."
    assert [c["label"] for c in used_citations(answer, citations)] == ["S2", "S1"]
    assert used_citations("No sources used.", citations) == []


class RecordingLLM:
    def __init__(self):
        self.calls = []

    async def call(self, agent, messages, *, stream=False):
        self.calls.append((agent, messages, stream))
        return "reply"


async def test_answer_chain_is_lcel_and_routes_through_llm() -> None:
    from langchain_core.runnables import Runnable

    from app.rag.answer import build_answer_chain

    llm = RecordingLLM()
    chain = build_answer_chain(llm, stream=True)
    assert isinstance(chain, Runnable)
    assert await chain.ainvoke({"context": "[S1] ctx", "question": "What is a stall?"}) == "reply"
    agent, messages, stream = llm.calls[0]
    assert agent == "research" and stream is True
    assert "Answer ONLY from the numbered sources" in messages[0].content
    assert "What is a stall?" in messages[-1].content
