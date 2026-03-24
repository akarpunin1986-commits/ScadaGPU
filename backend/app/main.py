import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from config import settings
from models import async_session, engine
from api.sites import router as sites_router
from api.devices import router as devices_router
from api.metrics import router as metrics_router
from api.maintenance import router as maintenance_router
from api.commands import router as commands_router
from api.bitrix import router as bitrix_router
from api.ai_parser import router as ai_parser_router
from api.history import router as history_router
from core.websocket import router as ws_router, redis_to_ws_bridge, maintenance_alerts_bridge, events_to_ws_bridge, sanek_reports_bridge, ai_analysis_bridge
from services.modbus_poller import ModbusPoller
from services.maintenance_scheduler import MaintenanceScheduler
from services.metrics_writer import MetricsWriter
from services.alarm_detector import AlarmDetector
from services.event_detector import EventDetector
from services.disk_manager import DiskSpaceManager
from api.power_limit import router as power_limit_router
from alarm_analytics.router import router as alarm_analytics_router
from alarm_analytics.detector import AlarmAnalyticsDetector
from api.knowledge import router as knowledge_router
from api.events import router as events_router
from api.economics import router as economics_router
from api.auth import router as auth_router
from api.bitrix_bot import router as bitrix_bot_router
from api.task_manager import router as task_manager_router
from api.maintenance_lifecycle import router as maintenance_lifecycle_router
from api.reports import router as reports_router
from api.sanek_chat import router as sanek_chat_router
from api.sanek_feedback import router as sanek_feedback_router
from api.sanek_goals import router as sanek_goals_router
from api.sanek_clarify import router as sanek_clarify_router
from api.data_api import router as data_api_router
from api.device_registry import router as device_registry_router
from api.dev_console import router as dev_console_router

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("scada.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("SCADA Backend starting... DEBUG=%s", settings.DEBUG)

    # Redis
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    app.state.redis = redis
    logger.info("Redis connected: %s", settings.REDIS_URL)

    # Load AI provider configs from DB into memory cache
    from api.ai_parser import load_ai_configs_from_db
    await load_ai_configs_from_db()

    # Poller (demo or production)
    if settings.DEMO_MODE:
        from services.demo_poller import DemoPoller
        poller = DemoPoller(redis)
        logger.info("DEMO_MODE enabled — using DemoPoller")
    else:
        poller = ModbusPoller(redis, async_session)
        logger.info("Production mode — using ModbusPoller")
    app.state.poller = poller
    poller_task = asyncio.create_task(poller.start())

    # Redis → WebSocket bridge
    ws_bridge_task = asyncio.create_task(redis_to_ws_bridge(redis))

    # Maintenance scheduler
    scheduler = MaintenanceScheduler(redis, async_session)
    app.state.maintenance_scheduler = scheduler
    scheduler_task = asyncio.create_task(scheduler.start())

    # Maintenance alerts → WebSocket bridge
    alerts_bridge_task = asyncio.create_task(maintenance_alerts_bridge(redis))

    # Phase 6 — Metrics persistence
    mw = MetricsWriter(
        redis, async_session,
        batch_size=settings.METRICS_WRITER_BATCH_SIZE,
        flush_interval=settings.METRICS_WRITER_FLUSH_INTERVAL,
    )
    app.state.metrics_writer = mw
    mw_task = asyncio.create_task(mw.start())

    # Phase 6 — Alarm detector
    ad = AlarmDetector(redis, async_session)
    app.state.alarm_detector = ad
    ad_task = asyncio.create_task(ad.start())

    # Event detector (SCADA event journal)
    ed = EventDetector(redis, async_session)
    app.state.event_detector = ed
    ed_task = asyncio.create_task(ed.start())

    # Events → WebSocket bridge
    events_bridge_task = asyncio.create_task(events_to_ws_bridge(redis))

    # Phase 6 — Disk space manager
    dm = DiskSpaceManager(
        async_session,
        check_interval=settings.DISK_CHECK_INTERVAL,
        max_db_size_mb=settings.DISK_MAX_DB_SIZE_MB,
        cleanup_threshold_pct=settings.DISK_CLEANUP_THRESHOLD_PCT,
        cleanup_batch_size=settings.DISK_CLEANUP_BATCH_SIZE,
    )
    app.state.disk_manager = dm
    dm_task = asyncio.create_task(dm.start())

    # Alarm Analytics — isolated module (detects individual alarm bits)
    aa_detector = AlarmAnalyticsDetector(redis, async_session)
    app.state.alarm_analytics_detector = aa_detector
    aa_task = asyncio.create_task(aa_detector.start())

    # SanekAgent reports → WebSocket bridge
    sanek_bridge_task = asyncio.create_task(sanek_reports_bridge(redis))

    # AI analysis → WebSocket bridge
    ai_analysis_bridge_task = asyncio.create_task(ai_analysis_bridge(redis))

    # SanekAgent — autonomous AI incident analysis (fully isolated)
    sanek_agent_module = None
    sanek_agent_task = None
    if settings.SANEK_AGENT_ENABLED:
        from services.sanek_agent import SanekAgentModule
        sanek_agent_module = SanekAgentModule(redis, async_session)
        app.state.sanek_agent = sanek_agent_module
        sanek_agent_task = asyncio.create_task(sanek_agent_module.start())
        logger.info("SanekAgent module enabled")
    else:
        logger.info("SanekAgent module DISABLED (SANEK_AGENT_ENABLED=false)")

    # Bitrix24 integration — fully isolated module
    b24_module = None
    b24_task = None
    if settings.BITRIX24_ENABLED:
        from services.bitrix24 import Bitrix24Module
        b24_module = Bitrix24Module(redis, async_session)
        app.state.bitrix24_module = b24_module
        b24_task = asyncio.create_task(b24_module.start())
        logger.info("Bitrix24 module enabled")
    else:
        logger.info("Bitrix24 module DISABLED (BITRIX24_ENABLED=false)")

    yield

    # Shutdown
    logger.info("SCADA Backend shutting down...")
    await poller.stop()
    await scheduler.stop()
    await mw.stop()
    await ad.stop()
    await ed.stop()
    await dm.stop()
    await aa_detector.stop()
    if sanek_agent_module:
        await sanek_agent_module.stop()
    if b24_module:
        await b24_module.stop()

    all_tasks = [
        poller_task, ws_bridge_task, scheduler_task, alerts_bridge_task,
        mw_task, ad_task, ed_task, events_bridge_task, dm_task, aa_task,
        sanek_bridge_task, ai_analysis_bridge_task,
    ]
    if sanek_agent_task:
        all_tasks.append(sanek_agent_task)
    if b24_task:
        all_tasks.append(b24_task)
    for t in all_tasks:
        t.cancel()
    for t in all_tasks:
        try:
            await t
        except asyncio.CancelledError:
            pass

    await redis.close()
    await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPI(
    title="SCADA GPU API",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sites_router)
app.include_router(devices_router)
app.include_router(metrics_router)
app.include_router(maintenance_router)
app.include_router(commands_router)
app.include_router(bitrix_router)
app.include_router(ai_parser_router)
app.include_router(history_router)
app.include_router(ws_router)
app.include_router(power_limit_router)
app.include_router(alarm_analytics_router)
app.include_router(knowledge_router)
app.include_router(events_router)
app.include_router(economics_router)
app.include_router(auth_router)
app.include_router(bitrix_bot_router)
app.include_router(task_manager_router)
app.include_router(maintenance_lifecycle_router)
app.include_router(reports_router)
app.include_router(sanek_chat_router)
app.include_router(sanek_feedback_router)
app.include_router(sanek_goals_router)
app.include_router(sanek_clarify_router)
app.include_router(data_api_router)
app.include_router(device_registry_router)
app.include_router(dev_console_router)

# SanekAgent API router (always available — shows reports even if agent disabled)
from api.sanek_agent import router as sanek_agent_router
app.include_router(sanek_agent_router)

# Bitrix24 module router (conditional)
if settings.BITRIX24_ENABLED:
    from api.bitrix24 import router as bitrix24_module_router
    app.include_router(bitrix24_module_router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.3.0"}
