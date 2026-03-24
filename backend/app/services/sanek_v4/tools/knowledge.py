"""
САНЁК v4 — Knowledge tools.

search_knowledge — search SmartGen manuals AND SOP experience entries
get_alarm_reference — structured alarm code lookup
"""
from __future__ import annotations

import logging

from sqlalchemy import select, or_, func

from models.base import async_session
from services.sanek_v4.tools import registry

logger = logging.getLogger("sanek_v4.tools.knowledge")


# ═══════════════════════════════════════════════════════════════
# TOOL: search_knowledge
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="search_knowledge",
    description=(
        "Поиск по базе знаний ScadaGPU: документация SmartGen (HGM9520N, HGM9560), "
        "руководства по эксплуатации, описания алармов, "
        "И накопленный опыт из решённых инцидентов (SOP). "
        "SOP результаты помечены source='experience' и содержат реальный диагноз + решение. "
        "Используй когда нужно: понять причину проблемы, найти прошлое решение, "
        "проверить спецификации оборудования."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Поисковый запрос на русском или английском. "
                    "Примеры: 'coolant temperature high alarm', "
                    "'допустимое давление масла', 'процедура ТО-1'."
                ),
            },
            "category": {
                "type": "string",
                "enum": ["all", "hgm9520n_manual", "hgm9560_manual", "general"],
                "description": "Категория для сужения поиска. По умолчанию 'all'.",
            },
            "top_k": {
                "type": "integer",
                "description": "Количество результатов (1-10). По умолчанию 5.",
            },
        },
        "required": ["query"],
    },
)
async def search_knowledge(
    query: str,
    category: str = "all",
    top_k: int = 5,
) -> dict:
    """Search knowledge base: ChromaDB RAG first, ILIKE fallback."""
    from config import settings

    top_k = max(1, min(10, top_k))
    results = []

    # ── ChromaDB RAG (primary) ──
    if getattr(settings, "SANEK_RAG_ENABLED", False):
        try:
            rag_results = await _search_chromadb(query, top_k=top_k)
            if rag_results:
                results.extend(rag_results)
                logger.debug("ChromaDB returned %d results for '%s'", len(rag_results), query[:50])
        except Exception as e:
            logger.warning("ChromaDB RAG failed, falling back to ILIKE: %s", e)

    # ── ILIKE fallback (if RAG returned nothing or disabled) ──
    if not results:
        results = await _search_ilike(query, category=category, top_k=top_k)

    # ── Search SOP entries (experience) ──
    sop_results = await _search_sop(keywords, top_k=3)
    for sop in sop_results:
        results.append(sop)

    # Sort: high-confidence SOP first, then docs by score
    results.sort(key=lambda r: (
        1 if r.get("source") == "experience" and r.get("confidence", 0) >= 0.7 else 0,
        r.get("relevance_score", 0),
    ), reverse=True)

    return {
        "query": query,
        "count": len(results),
        "results": results[:top_k],
        "sources": {
            "documentation": len(results) - len(sop_results),
            "experience_sop": len(sop_results),
        },
    }


async def _search_chromadb(query: str, top_k: int = 5) -> list[dict]:
    """Search ChromaDB vector store."""
    import httpx
    from config import settings

    url = f"{settings.CHROMADB_URL}/api/v1/collections"
    async with httpx.AsyncClient(timeout=10) as client:
        # Get collection ID
        colls = (await client.get(url)).json()
        coll_id = None
        for c in colls:
            if c["name"] == settings.CHROMADB_COLLECTION:
                coll_id = c["id"]
                break
        if not coll_id:
            return []

        # Query
        resp = await client.post(
            f"{url}/{coll_id}/query",
            json={"query_texts": [query], "n_results": top_k, "include": ["documents", "metadatas", "distances"]},
        )
        data = resp.json()

    documents = data.get("documents", [[]])[0]
    metadatas = data.get("metadatas", [[]])[0]
    distances = data.get("distances", [[]])[0]

    results = []
    for doc, meta, dist in zip(documents, metadatas, distances):
        # ChromaDB returns L2 distance; convert to similarity score
        score = max(0, 1 - dist) if dist is not None else 0.5
        results.append({
            "title": (meta or {}).get("title", ""),
            "content": doc[:1500] if doc else "",
            "category": (meta or {}).get("category", ""),
            "source": "chromadb",
            "relevance_score": round(score, 3),
        })

    return results


async def _search_ilike(query: str, category: str = "all", top_k: int = 5) -> list[dict]:
    """Fallback: ILIKE search in ai_knowledge_chunks table."""
    from models.ai_knowledge import AiKnowledgeChunk

    keywords = [w.strip().lower() for w in query.split() if len(w.strip()) >= 3]
    if not keywords:
        return []

    async with async_session() as db:
        conditions = []
        for kw in keywords[:5]:
            conditions.append(
                or_(
                    func.lower(AiKnowledgeChunk.content).contains(kw),
                    func.lower(AiKnowledgeChunk.title).contains(kw),
                )
            )

        query_stmt = select(AiKnowledgeChunk).where(or_(*conditions))
        if category != "all":
            query_stmt = query_stmt.where(AiKnowledgeChunk.category == category)
        query_stmt = query_stmt.limit(top_k * 3)
        rows = (await db.execute(query_stmt)).scalars().all()

    ranked = []
    for chunk in rows:
        text_lower = (chunk.content or "").lower() + " " + (chunk.title or "").lower()
        score = sum(1 for kw in keywords if kw in text_lower)
        ranked.append((score, chunk))

    ranked.sort(key=lambda x: -x[0])
    results = []
    for score, chunk in ranked[:top_k]:
        results.append({
            "title": chunk.title,
            "content": chunk.content[:1500] if chunk.content else "",
            "category": chunk.category,
            "source": chunk.source_filename,
            "relevance_score": score,
        })

    return results


async def _search_sop(keywords: list[str], top_k: int = 3) -> list[dict]:
    """Search SOP entries from past resolved incidents."""
    try:
        from models.sanek_sop_entry import SanekSopEntry
    except ImportError:
        return []

    try:
        async with async_session() as db:
            conditions = []
            for kw in keywords[:5]:
                conditions.append(
                    or_(
                        func.lower(SanekSopEntry.diagnosis).contains(kw),
                        func.lower(SanekSopEntry.resolution).contains(kw),
                        func.lower(SanekSopEntry.incident_type).contains(kw),
                        func.lower(func.coalesce(SanekSopEntry.alarm_code, "")).contains(kw),
                        func.lower(func.coalesce(SanekSopEntry.device_id, "")).contains(kw),
                    )
                )

            if not conditions:
                return []

            query = (
                select(SanekSopEntry)
                .where(or_(*conditions))
                .where(SanekSopEntry.confidence >= 0.3)  # skip unreliable
                .order_by(SanekSopEntry.confidence.desc())
                .limit(top_k * 2)
            )
            rows = (await db.execute(query)).scalars().all()

        # Rank by keyword matches
        ranked = []
        for sop in rows:
            text = f"{sop.diagnosis} {sop.resolution} {sop.incident_type} {sop.alarm_code or ''} {sop.device_id or ''}".lower()
            score = sum(1 for kw in keywords if kw in text)
            ranked.append((score, sop))

        ranked.sort(key=lambda x: (-x[0], -x[1].confidence))

        results = []
        for score, sop in ranked[:top_k]:
            # Update times_referenced
            try:
                async with async_session() as db2:
                    await db2.execute(
                        SanekSopEntry.__table__.update()
                        .where(SanekSopEntry.id == sop.id)
                        .values(times_referenced=SanekSopEntry.times_referenced + 1, last_referenced_at=func.now())
                    )
                    await db2.commit()
            except Exception:
                pass

            results.append({
                "source": "experience",
                "sop_id": sop.id,
                "title": f"SOP: {sop.incident_type} — {sop.device_id or 'general'}",
                "content": f"Диагноз: {sop.diagnosis}\nРешение: {sop.resolution}",
                "confidence": sop.confidence,
                "times_used": sop.times_referenced,
                "date": sop.created_at.isoformat() if sop.created_at else None,
                "resolved_by": sop.resolved_by,
                "relevance_score": score + (2 if sop.confidence >= 0.7 else 0),
            })

        return results

    except Exception as e:
        logger.warning("SOP search error: %s", e)
        return []


# ═══════════════════════════════════════════════════════════════
# TOOL: get_alarm_reference
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="get_alarm_reference",
    description=(
        "Получить описание конкретного аларма из справочника SmartGen. "
        "Возвращает: что означает, возможные причины, рекомендуемые действия. "
        "Быстрее чем search_knowledge для конкретного кода аларма."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "alarm_code": {
                "type": "string",
                "description": (
                    "Код аларма. Примеры: 'high_coolant_temp', 'low_oil_pressure', "
                    "'over_speed', 'gen_over_voltage', 'alarm_common', 'alarm_shutdown'."
                ),
            },
            "controller_type": {
                "type": "string",
                "enum": ["HGM9520N", "HGM9560"],
                "description": "Тип контроллера (опционально).",
            },
        },
        "required": ["alarm_code"],
    },
)
async def get_alarm_reference(
    alarm_code: str,
    controller_type: str | None = None,
) -> dict:
    """Lookup structured alarm information."""
    from models.alarm_reference import SanekAlarmReference  # noqa

    async with async_session() as db:
        conditions = [
            func.lower(SanekAlarmReference.alarm_code) == alarm_code.lower()
        ]
        if controller_type:
            conditions.append(SanekAlarmReference.controller == controller_type)

        query = select(SanekAlarmReference).where(*conditions).limit(3)
        rows = (await db.execute(query)).scalars().all()

    if not rows:
        return {
            "alarm_code": alarm_code,
            "found": False,
            "message": f"Alarm '{alarm_code}' not found in reference. Try search_knowledge for documentation search.",
        }

    results = []
    for ref in rows:
        results.append({
            "alarm_code": ref.alarm_code,
            "alarm_name": ref.alarm_name_ru,
            "controller": ref.controller,
            "category": ref.category,
            "severity": ref.severity,
            "typical_causes": ref.typical_causes or [],
            "immediate_actions": ref.immediate_actions or [],
            "related_alarms": ref.related_alarms or [],
            "manual_reference": ref.manual_reference,
        })

    return {
        "alarm_code": alarm_code,
        "found": True,
        "references": results,
    }
