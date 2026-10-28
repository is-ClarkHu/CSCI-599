from __future__ import annotations

import re

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.prompt_values import PromptValue
from langchain_core.runnables import Runnable, RunnableLambda

from app.types import Chunk, Citation


RAG_SYSTEM_PROMPT = """You are the Research agent of an Ultimate (flying disc) rules assistant.
Answer ONLY from the numbered sources below. After every sentence that uses a source,
cite it as [S1], [S2], ... using the exact labels given. If the sources do not contain
the answer, say "The provided sources do not cover this." and stop. Do not invent rule
numbers. When WFDF and USA Ultimate rules differ, say which rulebook each statement is from.
Answer in the same language as the question."""

NO_CONTEXT_ANSWER = "The provided sources do not cover this, and live web search is unavailable right now."

WEB_CONTENT_LIMIT = 1500
SNIPPET_LIMIT = 300

_prompt = ChatPromptTemplate.from_messages([
    ("system", RAG_SYSTEM_PROMPT),
    ("human", "Sources:\n{context}\n\nQuestion: {question}"),
])


def build_context(chunks: list[Chunk], web: list[dict] | None = None) -> tuple[str, list[Citation]]:
    blocks: list[str] = []
    citations: list[Citation] = []
    for chunk in chunks:
        label = f"S{len(citations) + 1}"
        blocks.append(f"[{label}] {chunk['title']}, p.{chunk['page']} ({chunk['chunk_id']})\n{chunk['text']}\n")
        citations.append(Citation(label=label, kind="rag", ref=chunk["chunk_id"], title=chunk["title"],
                                  page=chunk["page"], url=chunk["source_url"],
                                  snippet=chunk["text"][:SNIPPET_LIMIT]))
    for item in web or []:
        label = f"S{len(citations) + 1}"
        content = (item.get("content") or "")[:WEB_CONTENT_LIMIT]
        blocks.append(f"[{label}] {item.get('title', 'Web result')} ({item['url']})\n{content}\n")
        citations.append(Citation(label=label, kind="web", ref=item["url"], title=item.get("title", "Web result"),
                                  page=None, url=item["url"], snippet=content[:SNIPPET_LIMIT]))
    return "\n".join(blocks), citations


def build_messages(question: str, context: str) -> list[BaseMessage]:
    return _prompt.invoke({"context": context, "question": question}).to_messages()


def build_answer_chain(llm, *, agent: str = "research", stream: bool = False) -> Runnable:
    """LCEL chain: {context, question} -> prompt -> RoutedLLM (routing + fallback) -> LLMReply."""

    async def call_llm(prompt_value: PromptValue):
        return await llm.call(agent, prompt_value.to_messages(), stream=stream)

    return _prompt | RunnableLambda(call_llm)


def used_citations(answer: str, citations: list[Citation]) -> list[Citation]:
    by_label = {c["label"]: c for c in citations}
    ordered: list[Citation] = []
    for label in re.findall(r"\[(S\d+)\]", answer):
        if label in by_label and by_label[label] not in ordered:
            ordered.append(by_label[label])
    return ordered
