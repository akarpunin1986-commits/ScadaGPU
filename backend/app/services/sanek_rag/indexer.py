"""RAG Indexer — syncs PostgreSQL knowledge chunks to ChromaDB.

Reads chunks from ai_knowledge_chunks table, upserts to ChromaDB,
and marks them as embedded in PostgreSQL.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.ai_knowledge import AiKnowledgeChunk
from services.sanek_rag.rag_retriever import RagRetriever

logger = logging.getLogger("scada.rag_indexer")

# Batch size for embedding operations
_BATCH_SIZE = 100


class RagIndexer:
    """Indexes knowledge chunks from PostgreSQL into ChromaDB."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        retriever: RagRetriever,
    ):
        self._session_factory = session_factory
        self._retriever = retriever

    async def index_all(self) -> int:
        """Full reindex: all chunks from DB into ChromaDB.

        Returns number of chunks indexed.
        """
        async with self._session_factory() as session:
            stmt = select(AiKnowledgeChunk).order_by(
                AiKnowledgeChunk.source_filename,
                AiKnowledgeChunk.chunk_index,
            )
            result = await session.execute(stmt)
            chunks = result.scalars().all()

        if not chunks:
            logger.info("RAG Indexer: no chunks to index")
            return 0

        total = await self._index_chunks(chunks)
        logger.info("RAG Indexer: full reindex complete, %d chunks indexed", total)
        return total

    async def index_new(self) -> int:
        """Incremental index: only chunks where embedded=False or NULL.

        Returns number of new chunks indexed.
        """
        async with self._session_factory() as session:
            stmt = (
                select(AiKnowledgeChunk)
                .where(
                    (AiKnowledgeChunk.embedded == False)  # noqa: E712
                    | (AiKnowledgeChunk.embedded.is_(None))
                )
                .order_by(
                    AiKnowledgeChunk.source_filename,
                    AiKnowledgeChunk.chunk_index,
                )
            )
            result = await session.execute(stmt)
            chunks = result.scalars().all()

        if not chunks:
            logger.info("RAG Indexer: no new chunks to index")
            return 0

        total = await self._index_chunks(chunks)
        logger.info("RAG Indexer: incremental index complete, %d new chunks", total)
        return total

    async def index_document(self, source_filename: str) -> int:
        """Index or reindex all chunks of a specific document.

        Returns number of chunks indexed.
        """
        async with self._session_factory() as session:
            stmt = (
                select(AiKnowledgeChunk)
                .where(AiKnowledgeChunk.source_filename == source_filename)
                .order_by(AiKnowledgeChunk.chunk_index)
            )
            result = await session.execute(stmt)
            chunks = result.scalars().all()

        if not chunks:
            return 0

        total = await self._index_chunks(chunks)
        logger.info(
            "RAG Indexer: indexed %d chunks for document %s",
            total, source_filename,
        )
        return total

    async def _index_chunks(self, chunks: list[AiKnowledgeChunk]) -> int:
        """Process chunks in batches: upsert to ChromaDB, mark as embedded in DB."""
        total = 0
        indexed_ids: list[int] = []

        for i in range(0, len(chunks), _BATCH_SIZE):
            batch = chunks[i : i + _BATCH_SIZE]

            # Prepare for ChromaDB upsert
            chroma_docs = []
            for chunk in batch:
                device_type = self._detect_device_type(chunk.source_filename or "")
                chroma_docs.append({
                    "id": chunk.id,
                    "content": chunk.content or "",
                    "metadata": {
                        "title": chunk.title or "",
                        "category": chunk.category or "",
                        "source_filename": chunk.source_filename or "",
                        "chunk_index": chunk.chunk_index or 0,
                        "device_type": device_type,
                    },
                })

            count = await self._retriever.add_documents(chroma_docs)
            if count > 0:
                indexed_ids.extend(c.id for c in batch)
                total += count

        # Mark as embedded in PostgreSQL
        if indexed_ids:
            await self._mark_embedded(indexed_ids)

        return total

    async def _mark_embedded(self, chunk_ids: list[int]) -> None:
        """Update embedded=True for given chunk IDs in PostgreSQL."""
        async with self._session_factory() as session:
            stmt = (
                update(AiKnowledgeChunk)
                .where(AiKnowledgeChunk.id.in_(chunk_ids))
                .values(
                    embedded=True,
                    embedded_at=datetime.utcnow(),
                )
            )
            await session.execute(stmt)
            await session.commit()

    @staticmethod
    def _detect_device_type(filename: str) -> str:
        """Detect device type from filename."""
        upper = filename.upper()
        if "HGM9520" in upper or "9520" in upper:
            return "HGM9520N"
        if "HGM9560" in upper or "9560" in upper:
            return "HGM9560"
        if "SECM70" in upper or "SECM" in upper:
            return "SECM70"
        return "general"
