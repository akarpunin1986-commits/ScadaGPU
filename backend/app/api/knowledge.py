"""AI Knowledge Base API — upload manuals, search, list, delete.

POST /api/ai/knowledge/upload  — upload PDF/DOCX → extract → chunk → store
GET  /api/ai/knowledge/        — list uploaded documents
DELETE /api/ai/knowledge/{filename} — delete document chunks
GET  /api/ai/knowledge/search  — keyword search
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_session
from services.knowledge_base import (
    add_chunks,
    delete_document,
    get_documents,
    search_knowledge,
    split_into_chunks,
)

router = APIRouter(prefix="/api/ai/knowledge", tags=["ai-knowledge"])
logger = logging.getLogger("scada.api.knowledge")

# Max upload size ~20 MB
MAX_UPLOAD_SIZE = 20 * 1024 * 1024


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class DocumentOut(BaseModel):
    source_filename: str
    category: str
    chunk_count: int
    created_at: Optional[str] = None


class UploadResult(BaseModel):
    success: bool
    filename: str
    chunks_stored: int
    error: str = ""


class SearchResult(BaseModel):
    id: int
    title: str
    content: str
    category: str
    source_filename: str


class DeleteResult(BaseModel):
    success: bool
    filename: str
    chunks_deleted: int


# ---------------------------------------------------------------------------
# Text extraction (reuse pypdf / python-docx)
# ---------------------------------------------------------------------------

def _extract_text(file_bytes: bytes, filename: str) -> str:
    """Extract text from PDF or DOCX."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "pdf":
        return _extract_pdf(file_bytes)
    elif ext in ("docx", "doc"):
        return _extract_docx(file_bytes)
    elif ext == "txt":
        return file_bytes.decode("utf-8", errors="replace")
    else:
        raise ValueError(f"Формат .{ext} не поддерживается. Используйте PDF, DOCX или TXT.")


def _extract_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF using pypdf."""
    import io
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("pypdf не установлен")

    reader = PdfReader(io.BytesIO(file_bytes))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n\n".join(pages)


def _extract_docx(file_bytes: bytes) -> str:
    """Extract text from DOCX using python-docx."""
    import io
    try:
        from docx import Document
    except ImportError:
        raise RuntimeError("python-docx не установлен")

    doc = Document(io.BytesIO(file_bytes))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/upload", response_model=UploadResult)
async def upload_document(
    file: UploadFile = File(...),
    category: str = Form("general"),
    title: str = Form(""),
    session: AsyncSession = Depends(get_session),
) -> UploadResult:
    """Upload PDF/DOCX/TXT → extract text → chunk → store in DB."""
    filename = file.filename or "unknown"
    logger.info("Knowledge upload: %s (category=%s)", filename, category)

    try:
        file_bytes = await file.read()
        if len(file_bytes) > MAX_UPLOAD_SIZE:
            return UploadResult(
                success=False, filename=filename, chunks_stored=0,
                error=f"Файл слишком большой ({len(file_bytes) // 1024 // 1024} МБ). Максимум 20 МБ.",
            )

        # Extract text
        text = _extract_text(file_bytes, filename)
        if not text.strip():
            return UploadResult(
                success=False, filename=filename, chunks_stored=0,
                error="Не удалось извлечь текст из файла. Файл может быть пустым или содержать только изображения.",
            )

        # Chunk
        chunks = split_into_chunks(text, chunk_size=2000, overlap=200)
        logger.info("Extracted %d chars, split into %d chunks", len(text), len(chunks))

        # Store
        stored = await add_chunks(session, chunks, filename, category, title)

        return UploadResult(success=True, filename=filename, chunks_stored=stored)

    except ValueError as e:
        return UploadResult(success=False, filename=filename, chunks_stored=0, error=str(e))
    except Exception as e:
        logger.error("Upload error: %s", e, exc_info=True)
        return UploadResult(
            success=False, filename=filename, chunks_stored=0,
            error=f"Ошибка обработки: {str(e)[:200]}",
        )


@router.get("/", response_model=list[DocumentOut])
async def list_documents(
    session: AsyncSession = Depends(get_session),
) -> list[DocumentOut]:
    """List all uploaded documents grouped by filename."""
    docs = await get_documents(session)
    return [DocumentOut(**d) for d in docs]


@router.delete("/{filename:path}", response_model=DeleteResult)
async def remove_document(
    filename: str,
    session: AsyncSession = Depends(get_session),
) -> DeleteResult:
    """Delete all chunks of a document."""
    deleted = await delete_document(session, filename)
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"Документ '{filename}' не найден")
    return DeleteResult(success=True, filename=filename, chunks_deleted=deleted)


@router.get("/search", response_model=list[SearchResult])
async def search(
    q: str = Query(..., min_length=2, description="Поисковый запрос"),
    category: Optional[str] = Query(None, description="Фильтр по категории"),
    limit: int = Query(5, le=20),
    session: AsyncSession = Depends(get_session),
) -> list[SearchResult]:
    """Search knowledge base by keywords."""
    results = await search_knowledge(session, q, category=category, limit=limit)
    return [SearchResult(**r) for r in results]
