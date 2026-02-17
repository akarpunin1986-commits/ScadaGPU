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
from core.websocket import router as ws_router, redis_to_ws_bridge, maintenance_alerts_bridge
from services.modbus_poller import ModbusPoller
from services.maintenance_scheduler import MaintenanceScheduler

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

    yield

    # Shutdown
    logger.info("SCADA Backend shutting down...")
    await poller.stop()
    await scheduler.stop()
    poller_task.cancel()
    ws_bridge_task.cancel()
    scheduler_task.cancel()
    alerts_bridge_task.cancel()

    for task in [poller_task, ws_bridge_task, scheduler_task, alerts_bridge_task]:
        try:
            await task
        except asyncio.CancelledError:
            pass

    await redis.close()
    await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPI(
    title="SCADA GPU API",
    version="0.2.0",
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
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.2.0"}
