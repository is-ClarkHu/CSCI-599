"""Build corpus/chunks.jsonl from corpus/raw/*.pdf, then (re)build the Chroma index.

Usage:
  python -m scripts.ingest                # chunk PDFs + embed + index
  python -m scripts.ingest --from-jsonl   # skip PDFs; index the committed chunks.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from datetime import date
from pathlib import Path

from app.config import Settings
from app.rag.chunking import chunk_pages, extract_pages, read_chunks_jsonl, write_chunks_jsonl
from app.rag.store import ChunkStore
from scripts.download_corpus import load_manifest, target_path


ROOT = Path(__file__).resolve().parents[1]
CHUNKS = ROOT / "corpus" / "chunks.jsonl"
INDEX_MANIFEST = ROOT / "corpus" / "index_manifest.json"


def write_index_manifest(settings: Settings, chunk_count: int) -> None:
    """Record what the prebuilt Chroma index was built from, so stale indexes are detectable."""

    INDEX_MANIFEST.write_text(json.dumps({
        "chunks_sha256": hashlib.sha256(CHUNKS.read_bytes()).hexdigest(),
        "chunk_count": chunk_count,
        "embedding_model": settings.openai_embedding_model,
        "collection": settings.chroma_collection,
        "built_on": date.today().isoformat(),
    }, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-jsonl", action="store_true")
    args = parser.parse_args()
    started = time.perf_counter()

    if args.from_jsonl:
        chunks = read_chunks_jsonl(CHUNKS)
    else:
        chunks = []
        for doc in load_manifest(ROOT / "corpus" / "manifest.json"):
            pdf = target_path(ROOT / "corpus" / "raw", doc)
            if not pdf.exists():
                raise SystemExit(f"Missing {pdf}; run `python -m scripts.download_corpus` first")
            doc_chunks = chunk_pages(doc, extract_pages(pdf))
            print(f"{doc['id']}: {len(doc_chunks)} chunks")
            chunks.extend(doc_chunks)
        write_chunks_jsonl(chunks, CHUNKS)

    settings = Settings()
    written = ChunkStore(settings).build(chunks)
    write_index_manifest(settings, written)
    print(f"indexed {written} chunks in {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
