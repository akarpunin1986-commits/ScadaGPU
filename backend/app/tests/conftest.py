"""Shared fixtures for Sanek AI Agent test suite."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import settings
from models.sop_procedure import SopProcedure
from services.agent_sop_engine import (
    ActionPlan,
    SopEngine,
    SopLookupContext,
)


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
async def db_engine():
    """Async engine connected to test PostgreSQL (per-test to avoid loop issues)."""
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_size=2,
        max_overflow=0,
    )
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_connection(db_engine: AsyncEngine):
    """Per-test connection with transaction rollback for isolation."""
    async with db_engine.connect() as conn:
        trans = await conn.begin()
        try:
            yield conn
        finally:
            await trans.rollback()


@pytest.fixture
async def session_factory(db_connection):
    """async_sessionmaker bound to the per-test connection (rollback isolation)."""
    factory = async_sessionmaker(
        bind=db_connection,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return factory


@pytest.fixture
async def db_session(session_factory):
    """A single async session for direct DB operations in tests."""
    async with session_factory() as session:
        yield session


@pytest.fixture
async def sop_engine(session_factory):
    """Fresh SopEngine instance per test."""
    return SopEngine(session_factory)


# ---------------------------------------------------------------------------
# Seed data fixture
# ---------------------------------------------------------------------------
SEED_PROCEDURES = [
    {
        "alarm_code": "SHUTDOWN",
        "device_type": "generator",
        "root_cause": None,
        "severity": "critical",
        "version": 1,
        "description": "Emergency shutdown procedure for generator",
        "actions_json": [
            {"step": 1, "instruction": "Verify emergency shutdown cause on HMI panel",
             "ui_control": "devices/{device}/status/shutdown_reason",
             "expected_state": "SHUTDOWN_ACTIVE",
             "verification": "Shutdown reason displayed on HMI",
             "safety_note": "Do not reset until cause is identified"},
            {"step": 2, "instruction": "Check generator protection relay status",
             "ui_control": "devices/{device}/protection/relay_status",
             "expected_state": "TRIPPED",
             "verification": "Relay code matches shutdown cause",
             "safety_note": None},
            {"step": 3, "instruction": "Verify fuel supply valve position — CLOSED",
             "ui_control": "devices/{device}/fuel/valve_position",
             "expected_state": "CLOSED",
             "verification": "Valve indicator shows CLOSED",
             "safety_note": "Ensure no fuel leaks before proceeding"},
            {"step": 4, "instruction": "Check coolant temperature below 60C",
             "ui_control": "devices/{device}/sensors/coolant_temp",
             "expected_state": "<60",
             "verification": "Temperature reading < 60C",
             "safety_note": "Wait for cooldown if temperature is above threshold"},
            {"step": 5, "instruction": "Reset protection relay and log incident",
             "ui_control": "devices/{device}/protection/reset",
             "expected_state": "READY",
             "verification": "Protection relay in READY state",
             "safety_note": "Obtain supervisor approval before reset"},
        ],
    },
    {
        "alarm_code": "TRIP_STOP",
        "device_type": "generator",
        "root_cause": None,
        "severity": "high",
        "version": 1,
        "description": "Generator trip stop — desynchronization recovery",
        "actions_json": [
            {"step": 1, "instruction": "Set generator synchronization mode to AUTO",
             "safety_note": None},
            {"step": 2, "instruction": "Verify phase angle difference < 5 degrees",
             "safety_note": "If delta > 10 deg, perform manual resynchronization"},
            {"step": 3, "instruction": "Verify generator voltage 400V +/-10V",
             "safety_note": None},
            {"step": 4, "instruction": "Verify frequency 50Hz +/-0.5Hz",
             "safety_note": None},
            {"step": 5, "instruction": "Close contactor K1",
             "safety_note": "Ensure all sync parameters are within limits before closing"},
        ],
    },
    {
        "alarm_code": "CONN_LOST",
        "device_type": "any",
        "root_cause": None,
        "severity": "high",
        "version": 1,
        "description": "Communication loss recovery procedure",
        "actions_json": [
            {"step": 1, "instruction": "Check network connectivity to device controller",
             "safety_note": None},
            {"step": 2, "instruction": "Verify Modbus/TCP gateway status",
             "safety_note": None},
            {"step": 3, "instruction": "Check last known device state in SCADA historian",
             "safety_note": "If device was in critical state before disconnect, dispatch field operator"},
            {"step": 4, "instruction": "Attempt communication restart via gateway reset",
             "safety_note": "Only one restart attempt; escalate if unsuccessful"},
        ],
    },
    {
        "alarm_code": "BLOCK",
        "device_type": "any",
        "root_cause": None,
        "severity": "medium",
        "version": 1,
        "description": "Device block/interlock active",
        "actions_json": [
            {"step": 1, "instruction": "Identify active interlock condition on HMI",
             "safety_note": "Do not bypass interlocks without engineering approval"},
            {"step": 2, "instruction": "Verify prerequisite conditions for interlock release",
             "safety_note": None},
            {"step": 3, "instruction": "Release interlock and confirm device returns to READY",
             "safety_note": "Monitor device for 5 minutes after release"},
        ],
    },
    {
        "alarm_code": "MAINTENANCE_OVERDUE",
        "device_type": "any",
        "root_cause": None,
        "severity": "low",
        "version": 1,
        "description": "Scheduled maintenance overdue",
        "actions_json": [
            {"step": 1, "instruction": "Review maintenance schedule and identify overdue tasks",
             "safety_note": None},
            {"step": 2, "instruction": "Create maintenance work order in CMMS",
             "safety_note": None},
            {"step": 3, "instruction": "Acknowledge alarm and set maintenance reminder for 24h",
             "safety_note": "Do not silence alarm without creating work order"},
        ],
    },
]


@pytest.fixture
async def seed_sop_procedures(db_session: AsyncSession):
    """Insert 5 seed SOP procedures into the test transaction."""
    records = []
    for proc in SEED_PROCEDURES:
        sop = SopProcedure(
            alarm_code=proc["alarm_code"],
            device_type=proc["device_type"],
            root_cause=proc["root_cause"],
            severity=proc["severity"],
            version=proc["version"],
            description=proc["description"],
            actions_json=proc["actions_json"],
        )
        db_session.add(sop)
        records.append(sop)
    await db_session.flush()
    return records


# ---------------------------------------------------------------------------
# Mock fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_llm_caller():
    """AsyncMock simulating _call_llm with valid JSON response."""
    return AsyncMock(return_value={
        "text": '[{"step": 1, "instruction": "Check relay status"}]',
        "provider": "openai",
        "model": "gpt-4o",
        "tokens": 150,
    })


@pytest.fixture
def make_sop_context(mock_llm_caller):
    """Factory for SopLookupContext with defaults."""
    def _make(
        incident_id: int = 1,
        alarm_code: str = "SHUTDOWN",
        device_type: str = "generator",
        device_name: str = "Generator 1",
        severity: str = "critical",
        cause: str = "",
        llm_caller=None,
    ) -> SopLookupContext:
        return SopLookupContext(
            incident_id=incident_id,
            alarm_code=alarm_code,
            device_type=device_type,
            device_name=device_name,
            severity=severity,
            cause=cause,
            llm_caller=llm_caller,
        )
    return _make


@pytest.fixture
def mock_sop_procedure():
    """Factory for mock SopProcedure objects."""
    _sentinel = object()

    def _make(
        id: int = 1,
        alarm_code: str = "SHUTDOWN",
        device_type: str = "generator",
        root_cause: str | None = None,
        version: int = 1,
        actions_json=_sentinel,
    ):
        sop = MagicMock(spec=SopProcedure)
        sop.id = id
        sop.alarm_code = alarm_code
        sop.device_type = device_type
        sop.root_cause = root_cause
        sop.version = version
        if actions_json is _sentinel:
            sop.actions_json = [{"step": 1, "instruction": "Check relay status"}]
        else:
            sop.actions_json = actions_json
        return sop
    return _make
