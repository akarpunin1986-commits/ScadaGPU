"""Knowledge Base service — text chunking + ILIKE search.

Used to store and retrieve manual text chunks for LLM context.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from sqlalchemy import select, and_, delete, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from models.ai_knowledge import AiKnowledgeChunk

logger = logging.getLogger("scada.knowledge_base")


def split_into_chunks(
    text: str,
    chunk_size: int = 2000,
    overlap: int = 200,
) -> list[str]:
    """Split text into overlapping chunks, breaking at paragraph or sentence boundaries.

    Args:
        text: Full document text.
        chunk_size: Target size per chunk (chars).
        overlap: Overlap between consecutive chunks.

    Returns:
        List of text chunks.
    """
    if not text or not text.strip():
        return []

    # Normalize whitespace
    text = text.strip()

    # Split into paragraphs first
    paragraphs = re.split(r"\n\s*\n", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        # If adding this paragraph exceeds chunk_size, finalize current chunk
        if current and len(current) + len(para) + 2 > chunk_size:
            chunks.append(current.strip())
            # Start new chunk with overlap from the end of current
            if overlap > 0 and len(current) > overlap:
                current = current[-overlap:] + "\n\n" + para
            else:
                current = para
        else:
            current = current + "\n\n" + para if current else para

    if current.strip():
        chunks.append(current.strip())

    # Handle single-paragraph massive text (no paragraph breaks)
    if len(chunks) == 1 and len(chunks[0]) > chunk_size * 2:
        big = chunks[0]
        chunks = []
        # Split by sentences
        sentences = re.split(r"(?<=[.!?])\s+", big)
        current = ""
        for sent in sentences:
            if current and len(current) + len(sent) + 1 > chunk_size:
                chunks.append(current.strip())
                if overlap > 0 and len(current) > overlap:
                    current = current[-overlap:] + " " + sent
                else:
                    current = sent
            else:
                current = current + " " + sent if current else sent
        if current.strip():
            chunks.append(current.strip())

    return chunks


def extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from alarm name/description for search.

    Args:
        text: Alarm name or description text.

    Returns:
        List of keywords (lowercase, length >= 3).
    """
    if not text:
        return []
    # Remove common stop-words (Russian + English)
    stop_words = {
        "and", "the", "for", "with", "from", "alarm", "error", "warning",
        "для", "при", "или", "это", "что", "как", "все", "его", "она",
        "они", "так", "уже", "еще", "нет", "это", "тоже", "был",
    }
    # Split by non-alphanumeric (keep Cyrillic)
    words = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+", text.lower())
    return [w for w in words if len(w) >= 3 and w not in stop_words]


async def search_knowledge(
    session: AsyncSession,
    query: str,
    category: Optional[str] = None,
    limit: int = 5,
) -> list[dict]:
    """Search knowledge base by keywords using ILIKE.

    Args:
        session: DB session.
        query: Search text (alarm name, description, etc.).
        category: Optional category filter.
        limit: Max results.

    Returns:
        List of dicts with id, title, content, category, source_filename.
    """
    keywords = extract_keywords(query)
    if not keywords:
        return []

    # Build ILIKE conditions for each keyword
    conditions = []
    for kw in keywords[:5]:  # Limit to 5 keywords
        pattern = f"%{kw}%"
        conditions.append(
            or_(
                AiKnowledgeChunk.content.ilike(pattern),
                AiKnowledgeChunk.title.ilike(pattern),
            )
        )

    stmt = select(AiKnowledgeChunk)
    filters = conditions  # OR between keyword matches would be too broad, use AND
    if category:
        filters.append(AiKnowledgeChunk.category == category)

    if filters:
        stmt = stmt.where(and_(*filters))

    stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    return [
        {
            "id": r.id,
            "title": r.title,
            "content": r.content,
            "category": r.category,
            "source_filename": r.source_filename,
        }
        for r in rows
    ]


async def get_documents(session: AsyncSession) -> list[dict]:
    """Get list of uploaded documents (grouped by filename).

    Returns:
        List of dicts with source_filename, category, chunk_count, created_at.
    """
    stmt = (
        select(
            AiKnowledgeChunk.source_filename,
            AiKnowledgeChunk.category,
            func.count(AiKnowledgeChunk.id).label("chunk_count"),
            func.min(AiKnowledgeChunk.created_at).label("created_at"),
        )
        .group_by(AiKnowledgeChunk.source_filename, AiKnowledgeChunk.category)
        .order_by(func.min(AiKnowledgeChunk.created_at).desc())
    )
    result = await session.execute(stmt)
    rows = result.all()
    return [
        {
            "source_filename": r.source_filename,
            "category": r.category,
            "chunk_count": r.chunk_count,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def delete_document(session: AsyncSession, filename: str) -> int:
    """Delete all chunks of a document by filename.

    Returns:
        Number of deleted chunks.
    """
    stmt = delete(AiKnowledgeChunk).where(
        AiKnowledgeChunk.source_filename == filename
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount


async def add_chunks(
    session: AsyncSession,
    chunks: list[str],
    filename: str,
    category: str,
    title: str = "",
) -> int:
    """Store text chunks in the knowledge base.

    Args:
        session: DB session.
        chunks: List of text chunks.
        filename: Source filename.
        category: Document category.
        title: Document title.

    Returns:
        Number of stored chunks.
    """
    if not chunks:
        return 0

    doc_title = title or filename
    objects = [
        AiKnowledgeChunk(
            category=category,
            title=doc_title,
            content=chunk,
            source_filename=filename,
            chunk_index=i,
        )
        for i, chunk in enumerate(chunks)
    ]
    session.add_all(objects)
    await session.commit()
    return len(objects)
