"""Integration tests for SopEngine.resolve() — full 4-tier resolution."""
from unittest.mock import AsyncMock

import pytest
from services.agent_sop_engine import SopEngine, SopLookupContext

pytestmark = pytest.mark.integration


class TestResolveTiers:
    async def test_tier2_db_hit_shutdown(self, sop_engine, seed_sop_procedures):
        """Tier 2: SHUTDOWN/generator → DB hit, confidence 0.70."""
        ctx = SopLookupContext(
            incident_id=1, alarm_code="SHUTDOWN", device_type="generator",
            device_name="Gen1",
        )
        plan = await sop_engine.resolve(ctx)
        assert plan.source == "db"
        assert plan.confidence == 0.70
        assert len(plan.actions) == 5
        assert plan.sop_id is not None

    async def test_tier3_db_hit_conn_lost(self, sop_engine, seed_sop_procedures):
        """Tier 3: CONN_LOST/transformer → finds device_type='any', confidence 0.50."""
        ctx = SopLookupContext(
            incident_id=2, alarm_code="CONN_LOST", device_type="transformer",
            device_name="TRF-1",
        )
        plan = await sop_engine.resolve(ctx)
        assert plan.source == "db"
        assert plan.confidence == 0.50

    async def test_tier4_llm_fallback(self, sop_engine, seed_sop_procedures):
        """Tier 4: Unknown alarm with LLM caller → LLM fallback."""
        mock_llm = AsyncMock(return_value={
            "text": '[{"step": 1, "instruction": "LLM generated step"}]',
            "provider": "openai", "model": "gpt-4o", "tokens": 50,
        })
        ctx = SopLookupContext(
            incident_id=3, alarm_code="UNKNOWN_ALARM", device_type="pump",
            device_name="Pump-1", llm_caller=mock_llm,
        )
        plan = await sop_engine.resolve(ctx)
        assert plan.source == "llm"
        assert plan.confidence == 0.40
        mock_llm.assert_called_once()

    async def test_no_sop_no_llm(self, sop_engine, seed_sop_procedures):
        """No SOP match and no LLM caller → safe fallback."""
        ctx = SopLookupContext(
            incident_id=4, alarm_code="UNKNOWN_ALARM", device_type="pump",
            device_name="Pump-1", llm_caller=None,
        )
        plan = await sop_engine.resolve(ctx)
        assert plan.source == "error"
        assert plan.confidence == 0.0
        assert "Escalate" in plan.actions[0]["instruction"]

    async def test_normalizes_input(self, sop_engine, seed_sop_procedures):
        """resolve() should normalize alarm_code and device_type."""
        ctx = SopLookupContext(
            incident_id=5, alarm_code=" shutdown ", device_type="Generator",
            device_name="Gen1",
        )
        plan = await sop_engine.resolve(ctx)
        assert plan.source == "db"
        assert plan.confidence == 0.70

    async def test_uses_cache_on_second_call(self, sop_engine, seed_sop_procedures):
        """Second resolve with same params should use cache."""
        ctx1 = SopLookupContext(
            incident_id=6, alarm_code="TRIP_STOP", device_type="generator",
        )
        ctx2 = SopLookupContext(
            incident_id=7, alarm_code="TRIP_STOP", device_type="generator",
        )
        plan1 = await sop_engine.resolve(ctx1)
        plan2 = await sop_engine.resolve(ctx2)
        assert plan1.sop_id == plan2.sop_id

    async def test_llm_returns_valid_json(self, sop_engine, seed_sop_procedures):
        """Full LLM fallback with valid JSON response."""
        mock_llm = AsyncMock(return_value={
            "text": '```json\n[{"step": 1, "instruction": "First"}, '
                    '{"step": 2, "instruction": "Second"}]\n```',
        })
        ctx = SopLookupContext(
            incident_id=8, alarm_code="RARE_ALARM", device_type="custom",
            llm_caller=mock_llm,
        )
        plan = await sop_engine.resolve(ctx)
        assert plan.source == "llm"
        assert len(plan.actions) == 2

    async def test_llm_returns_garbage(self, sop_engine, seed_sop_procedures):
        """LLM returns garbage → safe fallback."""
        mock_llm = AsyncMock(return_value={"text": "I cannot help with that."})
        ctx = SopLookupContext(
            incident_id=9, alarm_code="RARE_ALARM", device_type="custom",
            llm_caller=mock_llm,
        )
        plan = await sop_engine.resolve(ctx)
        assert plan.source == "error"
        assert plan.confidence == 0.0
