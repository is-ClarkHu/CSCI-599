from __future__ import annotations

import hashlib
import json
from pathlib import Path

import chromadb
import pytest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "corpus" / "index_manifest.json").read_text(encoding="utf-8"))


def test_index_manifest_matches_committed_chunks() -> None:
    data = (ROOT / "corpus" / "chunks.jsonl").read_bytes()
    assert hashlib.sha256(data).hexdigest() == MANIFEST["chunks_sha256"]
    assert MANIFEST["chunk_count"] == len([line for line in data.splitlines() if line.strip()])


def test_prebuilt_index_is_not_stale() -> None:
    index_dir = ROOT / "chroma_index"
    if not index_dir.exists():
        pytest.skip("chroma_index/ not built in this checkout")
    collection = chromadb.PersistentClient(path=str(index_dir)).get_collection(MANIFEST["collection"])
    assert collection.count() == MANIFEST["chunk_count"]
