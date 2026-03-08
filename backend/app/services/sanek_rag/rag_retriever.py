"""RAG Retriever — semantic vector search via ChromaDB.

Replaces ILIKE-based search in knowledge_base.py with cosine-similarity
vector search. Uses ChromaDB's built-in embedding model (all-MiniLM-L6-v2).
Query expansion via bilingual synonyms from knowledge_base._SYNONYMS.

Interface compatible with _tool_search_knowledge() in sanek_agent.py.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("scada.rag_retriever")


class RagRetriever:
    """ChromaDB HTTP client wrapper for knowledge base semantic search."""

    def __init__(
        self,
        host: str = "chromadb",
        port: int = 8000,
        collection_name: str = "knowledge_base",
    ):
        self._host = host
        self._port = port
        self._collection_name = collection_name
        self._client = None
        self._collection = None

    async def initialize(self) -> None:
        """Connect to ChromaDB and get or create collection."""
        import chromadb
        from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

        self._embedding_fn = ONNXMiniLM_L6_V2()
        self._client = chromadb.HttpClient(host=self._host, port=self._port)
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
            embedding_function=self._embedding_fn,
        )
        count = self._collection.count()
        logger.info(
            "RAG Retriever: connected to ChromaDB %s:%d, collection=%s, documents=%d",
            self._host, self._port, self._collection_name, count,
        )

    def _expand_query(self, query: str) -> str:
        """Expand query with bilingual synonyms from knowledge_base._SYNONYMS."""
        try:
            from services.knowledge_base import _SYNONYMS
        except ImportError:
            return query

        words = query.lower().split()
        extras: set[str] = set()
        for word in words:
            if len(word) < 3:
                continue
            for syn_key, syn_vals in _SYNONYMS.items():
                if word in syn_key.lower() or syn_key.lower() in word:
                    extras.add(syn_key)
                    for sv in syn_vals[:3]:
                        extras.add(sv)
                    break
        if extras:
            return f"{query} {' '.join(extras)}"
        return query

    async def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.3,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search. Returns list of dicts compatible with sanek_agent.

        Each result: {title, content, source, score, category}
        """
        if not self._collection:
            logger.warning("RAG Retriever: collection not initialized")
            return []

        expanded_query = self._expand_query(query)

        where_filter = {"category": category} if category else None

        try:
            results = self._collection.query(
                query_texts=[expanded_query],
                n_results=top_k,
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            logger.error("RAG Retriever: search failed: %s", exc)
            return []

        if not results or not results.get("ids") or not results["ids"][0]:
            return []

        output: list[dict[str, Any]] = []
        ids = results["ids"][0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for i, doc_id in enumerate(ids):
            # ChromaDB cosine distance: lower = more similar
            # Convert to similarity score: score = 1 - distance
            distance = distances[i] if i < len(distances) else 1.0
            score = max(0.0, 1.0 - distance)

            if score < min_score:
                continue

            metadata = metadatas[i] if i < len(metadatas) else {}
            content = documents[i] if i < len(documents) else ""

            output.append({
                "title": metadata.get("title", ""),
                "content": content[:800],
                "source": metadata.get("source_filename", ""),
                "score": round(score, 3),
                "category": metadata.get("category", ""),
            })

        output.sort(key=lambda x: x["score"], reverse=True)
        return output

    async def add_documents(
        self,
        chunks: list[dict[str, Any]],
    ) -> int:
        """Batch upsert chunks into ChromaDB.

        Each chunk dict must have: id, content, metadata (title, category, source_filename, chunk_index).
        Returns number of documents added.
        """
        if not self._collection or not chunks:
            return 0

        ids = [str(c["id"]) for c in chunks]
        documents = [c["content"] for c in chunks]
        metadatas = [c.get("metadata", {}) for c in chunks]

        try:
            self._collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )
            logger.info("RAG Retriever: upserted %d documents", len(ids))
            return len(ids)
        except Exception as exc:
            logger.error("RAG Retriever: upsert failed: %s", exc)
            return 0

    async def delete_by_source(self, source_filename: str) -> int:
        """Delete all chunks from a source file."""
        if not self._collection:
            return 0

        try:
            # Get IDs matching this source
            results = self._collection.get(
                where={"source_filename": source_filename},
                include=[],
            )
            if results and results.get("ids"):
                ids = results["ids"]
                self._collection.delete(ids=ids)
                logger.info("RAG Retriever: deleted %d chunks for %s", len(ids), source_filename)
                return len(ids)
            return 0
        except Exception as exc:
            logger.error("RAG Retriever: delete failed: %s", exc)
            return 0
