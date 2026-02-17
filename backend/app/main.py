from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from models import engine
from api.sites import router as sites_router
from api.devices import router as devices_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"SCADA Backend starting... DEBUG={settings.DEBUG}")
    yield
    await engine.dispose()
    print("SCADA Backend shutting down...")


app = FastAPI(
    title="SCADA GPU API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В проде заменить на конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sites_router)
app.include_router(devices_router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
