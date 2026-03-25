"""САНЁК v3 — Auto Knowledge Indexer. PDF → chunks → structured SOPs."""
from __future__ import annotations
import asyncio, hashlib, json, logging
from pathlib import Path
from sqlalchemy import select, and_
from models.base import async_session
from models.ai_knowledge import AiKnowledgeChunk
from models.sop_procedure import SopProcedure
from config import settings

logger = logging.getLogger("sanek.indexer")
DOCS_DIR = "/opt/scada/docs/manuals"
CHECK_INTERVAL = 3600
CHUNK_SIZE = 1500
OVERLAP = 200


class AutoKnowledgeIndexer:
    def __init__(self):
        self._indexed: set[str] = set()

    async def run_forever(self):
        logger.info("Indexer started, dir=%s", DOCS_DIR)
        try:
            async with async_session() as db:
                hashes = (await db.execute(select(AiKnowledgeChunk.source_filename).distinct())).scalars().all()
                self._indexed = set(h for h in hashes if h)
        except Exception:
            pass
        while True:
            try:
                await self._scan()
            except Exception as e:
                logger.error("Indexer: %s", e, exc_info=True)
            await asyncio.sleep(CHECK_INTERVAL)

    async def _scan(self):
        d = Path(DOCS_DIR)
        if not d.exists():
            return
        for pdf in d.glob("*.pdf"):
            if pdf.name in self._indexed:
                continue
            logger.info("Indexing: %s", pdf.name)
            try:
                import fitz
                doc = fitz.open(str(pdf))
                text = "".join(p.get_text() + "\n" for p in doc)
                doc.close()
            except ImportError:
                logger.error("pymupdf not installed")
                return
            except Exception as e:
                logger.error("PDF extract %s: %s", pdf.name, e)
                continue
            if len(text) < 100:
                continue
            chunks = []
            start, idx = 0, 0
            while start < len(text):
                end = start + CHUNK_SIZE
                ct = text[start:end]
                lp = ct.rfind(".")
                if lp > CHUNK_SIZE // 2:
                    end = start + lp + 1
                    ct = text[start:end]
                chunks.append({"title": f"{pdf.stem} — ч.{idx+1}", "content": ct.strip(), "idx": idx})
                start = end - OVERLAP
                idx += 1
            async with async_session() as db:
                for ch in chunks:
                    db.add(AiKnowledgeChunk(title=ch["title"], content=ch["content"], source_filename=pdf.name))
                await db.commit()
            self._indexed.add(pdf.name)
            logger.info("Indexed %s: %d chunks", pdf.name, len(chunks))

            # ═══ SELF-LEARNING: LLM extraction of structured SOPs ═══
            await self._extract_structured_knowledge(pdf.name, chunks)

    async def _extract_structured_knowledge(self, pdf_name: str, chunks: list[dict]):
        """Из chunks → structured SOPs через LLM (batch, не real-time)."""
        try:
            from openai import AsyncOpenAI
        except ImportError:
            logger.warning("openai not installed, skipping LLM extraction")
            return

        combined = "\n\n".join(ch["content"] for ch in chunks[:20])
        if len(combined) < 200:
            return

        try:
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=60)
            response = await client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{
                    "role": "system",
                    "content": """Ты — инженер SCADA. Из текста мануала извлеки:
1. Процедуры обслуживания (alarm_code, причина, шаги решения)
2. Нормальные диапазоны параметров (метрика, min, max, unit)
3. Предупреждения и ограничения

Ответь ТОЛЬКО JSON:
{
  "sops": [{"alarm_code": "...", "description": "...", "root_cause": "...",
            "actions": [{"step": 1, "action": "..."}]}],
  "normal_ranges": [{"metric": "...", "min": 0, "max": 0, "unit": "..."}],
  "warnings": ["..."]
}"""
                }, {
                    "role": "user",
                    "content": f"Мануал: {pdf_name}\n\n{combined}"
                }],
                temperature=0.1,
                max_tokens=2000,
                response_format={"type": "json_object"}
            )

            data = json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error("LLM extraction failed for %s: %s", pdf_name, e)
            return

        async with async_session() as db:
            for sop in data.get("sops", []):
                existing = (await db.execute(
                    select(SopProcedure).where(and_(
                        SopProcedure.alarm_code == sop.get("alarm_code", ""),
                        SopProcedure.source == "manual"
                    ) if hasattr(SopProcedure, 'source') else (
                        SopProcedure.alarm_code == sop.get("alarm_code", "")
                    ))
                )).scalar_one_or_none()
                if not existing:
                    sop_kwargs = dict(
                        alarm_code=sop.get("alarm_code", "unknown"),
                        device_type="generator",
                        description=sop.get("description", ""),
                        root_cause=sop.get("root_cause", ""),
                        actions_json=sop.get("actions", []),
                    )
                    if hasattr(SopProcedure, 'source'):
                        sop_kwargs["source"] = "manual"
                    db.add(SopProcedure(**sop_kwargs))

            # Записать нормальные диапазоны как learning_insights
            try:
                from models.learning_insight import LearningInsight
                for nr in data.get("normal_ranges", []):
                    db.add(LearningInsight(
                        insight_type="normal_range",
                        source="manual",
                        content=nr,
                        confidence=1.0,
                        sample_size=0
                    ))
            except ImportError:
                pass

            await db.commit()
        logger.info("Extracted %d SOPs, %d ranges from %s",
                    len(data.get("sops", [])), len(data.get("normal_ranges", [])), pdf_name)
