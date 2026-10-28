from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.rag.store import ChunkStore


class KeywordEmbeddings:
    """Deterministic 3-d embedding: counts of three keywords."""

    words = ("stall", "pull", "foul")

    def _vec(self, text: str) -> list[float]:
        lowered = text.lower()
        vec = [float(lowered.count(w)) + 0.01 for w in self.words]
        return vec

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def _chunk(cid: str, text: str) -> dict:
    return {"chunk_id": cid, "doc_id": "d", "title": "T", "page": 1, "text": text,
            "source_url": "https://x", "score": 0.0}


def test_build_and_search_ranks_by_similarity(tmp_path: Path) -> None:
    store = ChunkStore(Settings(_env_file=None, chroma_persist_dir=tmp_path), embeddings=KeywordEmbeddings())
    written = store.build([
        _chunk("d:p1:c0", "stall stall stall count"),
        _chunk("d:p1:c1", "the pull starts the point pull"),
        _chunk("d:p1:c2", "foul foul contact"),
    ], batch_size=2)
    assert written == 3 and store.count() == 3
    results = store.search("what is a stall", k=2)
    assert results[0]["chunk_id"] == "d:p1:c0"
    assert results[0]["score"] >= results[1]["score"]
    assert results[0]["page"] == 1 and results[0]["source_url"] == "https://x"


def test_rebuild_replaces_old_collection(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, chroma_persist_dir=tmp_path)
    store = ChunkStore(settings, embeddings=KeywordEmbeddings())
    store.build([_chunk("d:p1:c0", "stall")])
    store.build([_chunk("d:p2:c0", "pull")])
    assert store.count() == 1


def test_search_on_empty_store_returns_empty(tmp_path: Path) -> None:
    store = ChunkStore(Settings(_env_file=None, chroma_persist_dir=tmp_path), embeddings=KeywordEmbeddings())
    assert store.search("anything", k=5) == []
