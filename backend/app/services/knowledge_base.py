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
        "может", "быть", "когда", "где", "есть", "будет",
    }
    # Split by non-alphanumeric (keep Cyrillic)
    words = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+", text.lower())
    return [w for w in words if len(w) >= 3 and w not in stop_words]


# Bilingual synonym map for common SCADA terms (RU→EN, EN→RU)
_SYNONYMS: dict[str, list[str]] = {
    "перегрев": ["overheating", "overheat", "high temp", "температура"],
    "overheating": ["перегрев", "температура", "high temp"],
    "давление": ["pressure", "oil pressure", "масло"],
    "pressure": ["давление", "масло"],
    "масло": ["oil", "давление", "смазк"],
    "oil": ["масло", "давление", "смазк"],
    "топливо": ["fuel", "бак", "уровень"],
    "fuel": ["топливо", "бак"],
    "обороты": ["speed", "rpm", "двигатель"],
    "speed": ["обороты", "rpm", "скорость"],
    "напряжение": ["voltage", "вольт"],
    "voltage": ["напряжение", "вольт"],
    "ток": ["current", "ампер"],
    "current": ["ток", "ампер"],
    "перегрузка": ["overload", "over power", "overcurrent"],
    "overload": ["перегрузка", "over power"],
    "охлаждение": ["coolant", "радиатор", "ож"],
    "coolant": ["охлаждение", "радиатор", "ож", "температура"],
    "частота": ["frequency", "герц"],
    "frequency": ["частота", "герц"],
    "аккумулятор": ["battery", "батарея", "акб"],
    "battery": ["аккумулятор", "батарея", "акб"],
    "shutdown": ["останов", "остановка", "аварий", "protection", "trip"],
    "останов": ["shutdown", "стоп", "остановка", "protection"],
    "генератор": ["generator", "генер"],
    "generator": ["генератор", "генер"],
    "сброс": ["reset", "alarm reset"],
    "reset": ["сброс", "alarm reset"],
    "турбина": ["turbo", "турбо", "наддув"],
    "turbo": ["турбина", "турбо", "наддув"],
    # Alarm-specific terms for knowledge base search
    "alarm": ["авария", "ошибка", "защита", "fault", "warning"],
    "авария": ["alarm", "fault", "ошибка", "защита"],
    "protection": ["защита", "alarm", "trip", "отключение", "shutdown"],
    "защита": ["protection", "alarm", "trip", "shutdown"],
    "overspeed": ["обороты", "speed", "превышение оборотов"],
    "underspeed": ["обороты", "speed", "низкие обороты"],
    "overcurrent": ["перегрузка", "ток", "overload", "current"],
    "trip": ["отключение", "останов", "shutdown", "protection"],
    "блокировка": ["block", "interlock", "блокир"],
    "block": ["блокировка", "interlock", "блокир"],
}


def _expand_synonyms(keywords: list[str]) -> list[str]:
    """Expand keywords with bilingual synonyms for better search coverage."""
    expanded = list(keywords)
    for kw in keywords:
        for syn_key, syn_vals in _SYNONYMS.items():
            if kw in syn_key or syn_key in kw:
                for sv in syn_vals:
                    if sv not in expanded:
                        expanded.append(sv)
                break
    return expanded[:10]  # Cap at 10 total keywords


async def search_knowledge(
    session: AsyncSession,
    query: str,
    category: Optional[str] = None,
    limit: int = 5,
) -> list[dict]:
    """Search knowledge base by keywords using ILIKE.

    Uses two-pass strategy:
    1. Strict AND search (all keywords must match) — most relevant
    2. Relaxed OR search with synonym expansion — broader coverage

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

    # --- Pass 1: Strict AND search (original keywords) ---
    conditions = []
    for kw in keywords[:5]:
        pattern = f"%{kw}%"
        conditions.append(
            or_(
                AiKnowledgeChunk.content.ilike(pattern),
                AiKnowledgeChunk.title.ilike(pattern),
            )
        )

    stmt = select(AiKnowledgeChunk)
    filters = list(conditions)
    if category:
        filters.append(AiKnowledgeChunk.category == category)

    if filters:
        stmt = stmt.where(and_(*filters))

    stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    # If enough results, return them
    if len(rows) >= limit:
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

    # --- Pass 2: Relaxed OR search with synonyms ---
    seen_ids = {r.id for r in rows}
    remaining = limit - len(rows)

    expanded = _expand_synonyms(keywords)
    or_conditions = []
    for kw in expanded:
        pattern = f"%{kw}%"
        or_conditions.append(
            or_(
                AiKnowledgeChunk.content.ilike(pattern),
                AiKnowledgeChunk.title.ilike(pattern),
            )
        )

    stmt2 = select(AiKnowledgeChunk)
    filters2 = [or_(*or_conditions)]
    if category:
        filters2.append(AiKnowledgeChunk.category == category)
    if seen_ids:
        stmt2 = stmt2.where(
            and_(*filters2, AiKnowledgeChunk.id.notin_(seen_ids))
        )
    else:
        stmt2 = stmt2.where(and_(*filters2))

    stmt2 = stmt2.limit(remaining)
    result2 = await session.execute(stmt2)
    rows.extend(result2.scalars().all())

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
