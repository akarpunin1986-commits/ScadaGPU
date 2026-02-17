from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print(f"SCADA Backend starting... DEBUG={settings.DEBUG}")
    yield
    # Shutdown
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


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/sites")
async def list_sites():
    # TODO: Phase 1 — подключить к БД
    return {"sites": [], "message": "API работает. БД пока не подключена."}
