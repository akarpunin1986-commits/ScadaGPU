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
from core.websocket import router as ws_router, redis_to_ws_bridge
from services.modbus_poller import ModbusPoller

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

    yield

    # Shutdown
    logger.info("SCADA Backend shutting down...")
    await poller.stop()
    poller_task.cancel()
    ws_bridge_task.cancel()

    try:
        await poller_task
    except asyncio.CancelledError:
        pass

    try:
        await ws_bridge_task
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
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.2.0"}
