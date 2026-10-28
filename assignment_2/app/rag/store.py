from __future__ import annotations

import logging

import chromadb
from langchain_openai import OpenAIEmbeddings

from app.config import Settings
from app.types import Chunk


logger = logging.getLogger(__name__)


def embedding_text(chunk: Chunk) -> str:
    """Prefix the document title so WFDF, USA Ultimate, beach and 4s chunks stay distinguishable."""

    return f"{chunk['title']}\n{chunk['text']}"


class ChunkStore:
    """Chroma-backed chunk index; cosine distance, metadata carries citation fields."""

    def __init__(self, settings: Settings, embeddings: object | None = None) -> None:
        self.settings = settings
        self.embeddings = embeddings or OpenAIEmbeddings(
            model=settings.openai_embedding_model,
            api_key=settings.openai_api_key,
        )
        settings.chroma_path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(settings.chroma_path))

    def _collection(self):
        return self.client.get_or_create_collection(
            name=self.settings.chroma_collection,
            metadata={"hnsw:space": "cosine"},
        )

    def count(self) -> int:
        return self._collection().count()

    def build(self, chunks: list[Chunk], batch_size: int = 100) -> int:
        try:
            self.client.delete_collection(self.settings.chroma_collection)
        except Exception:  # collection did not exist yet
            pass
        collection = self._collection()
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start:start + batch_size]
            collection.add(
                ids=[c["chunk_id"] for c in batch],
                documents=[c["text"] for c in batch],
                embeddings=self.embeddings.embed_documents([embedding_text(c) for c in batch]),
                metadatas=[{"doc_id": c["doc_id"], "title": c["title"], "page": c["page"],
                            "source_url": c["source_url"]} for c in batch],
            )
            logger.info("Indexed %d/%d chunks", start + len(batch), len(chunks))
        return collection.count()

    def search(self, query: str, k: int) -> list[Chunk]:
        collection = self._collection()
        total = collection.count()
        if total == 0:
            return []
        result = collection.query(
            query_embeddings=[self.embeddings.embed_query(query)],
            n_results=min(k, total),
            include=["documents", "metadatas", "distances"],
        )
        chunks: list[Chunk] = []
        for cid, text, meta, distance in zip(
            result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]
        ):
            chunks.append(Chunk(chunk_id=cid, doc_id=meta["doc_id"], title=meta["title"],
                                page=int(meta["page"]), text=text, source_url=meta["source_url"],
                                score=round(1.0 - float(distance), 4)))
        return sorted(chunks, key=lambda c: c["score"], reverse=True)
