from __future__ import annotations

import json
import re
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.types import Chunk


CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
MIN_CHUNK_CHARS = 40

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=["\n\n", "\n", ". ", " ", ""],
)


def _normalize(text: str) -> str:
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def extract_pages(pdf_path: Path) -> list[str]:
    return [page.extract_text() or "" for page in PdfReader(pdf_path).pages]


def chunk_pages(doc: dict, pages: list[str]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page_number, raw in enumerate(pages, start=1):
        pieces = [p.strip() for p in _splitter.split_text(_normalize(raw))]
        kept = [p for p in pieces if len(p) >= MIN_CHUNK_CHARS]
        for index, text in enumerate(kept):
            chunks.append(Chunk(
                chunk_id=f"{doc['id']}:p{page_number}:c{index}",
                doc_id=doc["id"],
                title=doc["title"],
                page=page_number,
                text=text,
                source_url=doc["url"],
                score=0.0,
            ))
    return chunks


def write_chunks_jsonl(chunks: list[Chunk], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")


def read_chunks_jsonl(path: Path) -> list[Chunk]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]
