"""Integration tests for SopEngine with real PostgreSQL."""
import pytest
from sqlalchemy import select
from services.agent_sop_engine import SopEngine
from models.sop_procedure import SopProcedure

pytestmark = pytest.mark.integration


class TestSopEngineStart:
    async def test_start_success(self, sop_engine):
        await sop_engine.start()
        assert sop_engine._started is True

    async def test_start_idempotent(self, sop_engine):
        await sop_engine.start()
        await sop_engine.start()
        assert sop_engine._started is True


class TestQueryDbTiers:
    async def test_tier2_alarm_device_no_cause(self, sop_engine, seed_sop_procedures):
        """Tier 2: alarm + device_type, root_cause IS NULL."""
        result = await sop_engine._query_db("SHUTDOWN", "generator", "UNKNOWN")
        assert result is not None
        assert result.alarm_code == "SHUTDOWN"
        assert result.device_type == "generator"

    async def test_tier3_alarm_any_device(self, sop_engine, seed_sop_procedures):
        """Tier 3: alarm + device_type='any' when specific type not found."""
        result = await sop_engine._query_db("CONN_LOST", "transformer", "UNKNOWN")
        assert result is not None
        assert result.alarm_code == "CONN_LOST"
        assert result.device_type == "any"

    async def test_no_match(self, sop_engine, seed_sop_procedures):
        """No SOP found for unknown alarm."""
        result = await sop_engine._query_db("NONEXISTENT", "widget", "UNKNOWN")
        assert result is None

    async def test_tier_priority(self, sop_engine, seed_sop_procedures, db_session):
        """When tier 1 exists, it should be returned over tier 2/3."""
        # Insert a tier-1 SOP with exact root_cause
        exact_sop = SopProcedure(
            alarm_code="SHUTDOWN",
            device_type="generator",
            root_cause="OVERHEATING",
            severity="critical",
            version=2,
            actions_json=[{"step": 1, "instruction": "Exact match action"}],
        )
        db_session.add(exact_sop)
        await db_session.flush()

        result = await sop_engine._query_db("SHUTDOWN", "generator", "OVERHEATING")
        assert result is not None
        assert result.root_cause == "OVERHEATING"
        assert result.version == 2


class TestSeedData:
    async def test_shutdown_generator(self, sop_engine, seed_sop_procedures):
        sop = await sop_engine._query_db("SHUTDOWN", "generator", "UNKNOWN")
        assert sop is not None
        assert sop.severity == "critical"
        assert len(sop.actions_json) == 5

    async def test_trip_stop_generator(self, sop_engine, seed_sop_procedures):
        sop = await sop_engine._query_db("TRIP_STOP", "generator", "UNKNOWN")
        assert sop is not None
        assert sop.severity == "high"
        assert len(sop.actions_json) == 5

    async def test_conn_lost_any(self, sop_engine, seed_sop_procedures):
        sop = await sop_engine._query_db("CONN_LOST", "any", "UNKNOWN")
        assert sop is not None
        assert sop.severity == "high"
        assert len(sop.actions_json) == 4

    async def test_block_any(self, sop_engine, seed_sop_procedures):
        sop = await sop_engine._query_db("BLOCK", "any", "UNKNOWN")
        assert sop is not None
        assert sop.severity == "medium"
        assert len(sop.actions_json) == 3

    async def test_maintenance_overdue_any(self, sop_engine, seed_sop_procedures):
        sop = await sop_engine._query_db("MAINTENANCE_OVERDUE", "any", "UNKNOWN")
        assert sop is not None
        assert sop.severity == "low"
        assert len(sop.actions_json) == 3
