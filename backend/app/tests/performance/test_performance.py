"""Performance benchmark tests for SOP Engine."""
import asyncio
import json
import time
from unittest.mock import AsyncMock, patch

import pytest
from services.agent_sop_engine import SopEngine, SopLookupContext

pytestmark = pytest.mark.performance


class TestPerformance:
    async def test_cached_lookup_under_20ms(self, sop_engine, seed_sop_procedures):
        """Cached SOP lookup should complete in < 20ms."""
        # Warm up cache
        await sop_engine._lookup("SHUTDOWN", "generator", "UNKNOWN")

        start = time.perf_counter()
        await sop_engine._lookup("SHUTDOWN", "generator", "UNKNOWN")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 20, f"Cached lookup took {elapsed_ms:.1f}ms (> 20ms)"

    async def test_cold_lookup_under_20ms(self, sop_engine, seed_sop_procedures):
        """Cold (DB) SOP lookup should complete in < 20ms."""
        start = time.perf_counter()
        await sop_engine._lookup("TRIP_STOP", "generator", "UNKNOWN")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 20, f"Cold lookup took {elapsed_ms:.1f}ms (> 20ms)"

    async def test_resolve_cached_under_5ms(self, sop_engine, seed_sop_procedures):
        """resolve() with cached SOP should complete in < 5ms."""
        ctx = SopLookupContext(
            incident_id=1, alarm_code="SHUTDOWN", device_type="generator",
        )
        # Warm up
        await sop_engine.resolve(ctx)

        start = time.perf_counter()
        await sop_engine.resolve(ctx)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 5, f"Cached resolve took {elapsed_ms:.1f}ms (> 5ms)"

    def test_parse_llm_large_input_under_10ms(self):
        """_parse_llm_actions with 4000-char input should complete in < 10ms."""
        actions = [{"step": i, "instruction": f"Step {i} " + "x" * 50} for i in range(20)]
        raw = json.dumps(actions)[:4000]

        start = time.perf_counter()
        SopEngine._parse_llm_actions(raw)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 10, f"Parse took {elapsed_ms:.1f}ms (> 10ms)"

    def test_build_plan_from_db_under_1ms(self, sop_engine, mock_sop_procedure):
        """_build_plan_from_db is pure computation, should take < 1ms."""
        sop = mock_sop_procedure(actions_json=[
            {"step": i, "instruction": f"Step {i}"} for i in range(10)
        ])
        ctx = SopLookupContext(
            incident_id=1, alarm_code="X", device_type="gen",
            device_name="Gen1", cause="test",
        )

        start = time.perf_counter()
        sop_engine._build_plan_from_db(ctx, sop, "gen", "X")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 1, f"build_plan took {elapsed_ms:.2f}ms (> 1ms)"

    async def test_pipeline_with_mock_llm_under_5s(self, sop_engine, seed_sop_procedures):
        """Full resolve() with LLM fallback (100ms mock delay) should take < 5s."""
        async def slow_llm(prompt):
            await asyncio.sleep(0.1)
            return {"text": '[{"step": 1, "instruction": "OK"}]'}

        ctx = SopLookupContext(
            incident_id=1, alarm_code="RARE_ALARM", device_type="custom",
            llm_caller=slow_llm,
        )

        start = time.perf_counter()
        plan = await sop_engine.resolve(ctx)
        elapsed_s = time.perf_counter() - start

        assert elapsed_s < 5, f"Pipeline took {elapsed_s:.1f}s (> 5s)"
        assert plan.source == "llm"
