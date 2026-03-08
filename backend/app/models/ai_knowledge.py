"""AI Knowledge Base — chunked text storage for manuals (SmartGen, etc.).

Each row = one text chunk (~2000 chars) from an uploaded PDF/DOCX.
Used by Sanek and /explain to provide manual context to LLM.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class AiKnowledgeChunk(Base):
    __tablename__ = "ai_knowledge_chunks"

    __table_args__ = (
        Index("ix_ai_knowledge_category", "category"),
        Index("ix_ai_knowledge_source", "source_filename"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(100))       # hgm9520n_manual, hgm9560_manual, general
    title: Mapped[str] = mapped_column(String(500))           # Document title / section heading
    content: Mapped[str] = mapped_column(Text)                # ~2000 chars text chunk
    source_filename: Mapped[str] = mapped_column(String(500)) # Original filename
    chunk_index: Mapped[int] = mapped_column()                # Order within document
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # RAG columns (Module 1)
    embedded: Mapped[bool | None] = mapped_column(Boolean, server_default="false", default=False)
    embedded_at: Mapped[datetime | None] = mapped_column(default=None)
    device_type: Mapped[str | None] = mapped_column(String(50), default=None)
    document_type: Mapped[str | None] = mapped_column(String(50), default=None)
    chroma_id: Mapped[str | None] = mapped_column(String(100), default=None)
