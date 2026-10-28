from __future__ import annotations

from pathlib import Path

from app.rag.chunking import chunk_pages, read_chunks_jsonl, write_chunks_jsonl


DOC = {"id": "wfdf-rules-2025", "title": "WFDF Rules", "url": "https://example.org/r.pdf"}


def test_chunks_never_cross_pages_and_keep_page_numbers() -> None:
    pages = ["A" * 50 + " stall count " * 200, "Page two talks about the pull. " * 10]
    chunks = chunk_pages(DOC, pages)
    assert {c["page"] for c in chunks} == {1, 2}
    assert all(len(c["text"]) <= 1000 for c in chunks)
    assert chunks[0]["chunk_id"] == "wfdf-rules-2025:p1:c0"
    page_two = [c for c in chunks if c["page"] == 2]
    assert page_two[0]["chunk_id"] == "wfdf-rules-2025:p2:c0"
    assert all(c["source_url"] == DOC["url"] and c["title"] == DOC["title"] for c in chunks)


def test_short_noise_chunks_are_dropped() -> None:
    assert chunk_pages(DOC, ["  12  ", "Page 3 of 40"]) == []


def test_whitespace_is_normalized() -> None:
    chunks = chunk_pages(DOC, ["Line one\n\n\n   Line   two that is long enough to keep around."])
    assert "   " not in chunks[0]["text"]


def test_jsonl_round_trip(tmp_path: Path) -> None:
    chunks = chunk_pages(DOC, ["The thrower has ten seconds to throw the disc. " * 3])
    path = tmp_path / "chunks.jsonl"
    write_chunks_jsonl(chunks, path)
    assert read_chunks_jsonl(path) == chunks
