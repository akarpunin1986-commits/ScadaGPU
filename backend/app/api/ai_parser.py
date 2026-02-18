"""
Phase 5 — AI agent API for parsing maintenance documents from Bitrix24 Disk.

Isolated module: separate router, no SCADA core dependencies.
If OPENAI_API_KEY is not configured, GET /api/ai/health returns available=false.
"""
import logging

from fastapi import APIRouter
from pydantic import BaseModel

from config import settings

router = APIRouter(prefix="/api/ai", tags=["ai-agent"])
logger = logging.getLogger("scada.ai_parser")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class ParseRequest(BaseModel):
    webhook_url: str
    file_id: int
    filename: str = ""


class ParsedTask(BaseModel):
    text: str
    is_critical: bool = False
    sort_order: int = 0


class ParsedInterval(BaseModel):
    code: str
    name: str
    hours: int
    sort_order: int = 0
    tasks: list[ParsedTask] = []


class ParseResponse(BaseModel):
    success: bool
    template_name: str = ""
    description: str = ""
    intervals: list[ParsedInterval] = []
    raw_text_preview: str = ""
    error: str | None = None


class HealthResponse(BaseModel):
    available: bool
    model: str = ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/health", response_model=HealthResponse)
async def ai_health():
    """Check if AI agent is configured and available."""
    available = bool(settings.OPENAI_API_KEY)
    return HealthResponse(
        available=available,
        model=settings.OPENAI_MODEL if available else "",
    )


@router.post("/parse", response_model=ParseResponse)
async def parse_maintenance_file(req: ParseRequest):
    """
    Download file from Bitrix24 Disk, extract text, parse with OpenAI.
    Returns structured maintenance intervals + tasks.
    """
    # Lazy import to avoid startup errors when openai is not installed
    from services.ai_agent import MaintenanceDocumentParser, AIAgentError

    if not settings.OPENAI_API_KEY:
        return ParseResponse(
            success=False,
            error="OPENAI_API_KEY не настроен. Добавьте ключ в .env файл.",
        )

    try:
        parser = MaintenanceDocumentParser()
        result = await parser.parse_bitrix_file(
            webhook_url=req.webhook_url,
            file_id=req.file_id,
            filename=req.filename or None,
        )

        # Convert raw dict to typed response
        intervals = []
        for iv_data in result.get("intervals", []):
            tasks = []
            for t_data in iv_data.get("tasks", []):
                tasks.append(ParsedTask(
                    text=t_data.get("text", ""),
                    is_critical=t_data.get("is_critical", False),
                    sort_order=t_data.get("sort_order", 0),
                ))
            intervals.append(ParsedInterval(
                code=iv_data.get("code", f"to{len(intervals)+1}"),
                name=iv_data.get("name", f"ТО-{len(intervals)+1}"),
                hours=iv_data.get("hours", 0),
                sort_order=iv_data.get("sort_order", len(intervals)),
                tasks=tasks,
            ))

        logger.info(
            "Successfully parsed %d intervals from file_id=%d",
            len(intervals), req.file_id,
        )

        return ParseResponse(
            success=True,
            template_name=result.get("name", "Регламент ТО"),
            description=result.get("description", ""),
            intervals=intervals,
            raw_text_preview=result.get("raw_text_preview", "")[:500],
        )

    except AIAgentError as e:
        logger.warning("AI agent error: %s", str(e))
        return ParseResponse(success=False, error=str(e))
    except Exception as e:
        logger.error("Unexpected error in AI parse: %s", str(e), exc_info=True)
        return ParseResponse(
            success=False,
            error=f"Непредвиденная ошибка: {str(e)}",
        )
