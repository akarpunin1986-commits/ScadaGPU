"""Unit tests for SopEngine._build_plan_from_llm."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from services.agent_sop_engine import SopEngine, SopLookupContext

pytestmark = pytest.mark.unit


@pytest.fixture
def engine(session_factory):
    return SopEngine(session_factory)


@pytest.fixture
def ctx_with_llm():
    def _make(llm_return=None, llm_side_effect=None):
        caller = AsyncMock()
        if llm_side_effect:
            caller.side_effect = llm_side_effect
        elif llm_return is not None:
            caller.return_value = llm_return
        else:
            caller.return_value = {
                "text": '[{"step": 1, "instruction": "Check relay"}]',
                "provider": "openai", "model": "gpt-4o", "tokens": 100,
            }
        return SopLookupContext(
            incident_id=1, alarm_code="TEST", device_type="generator",
            device_name="Gen1", cause="test cause", llm_caller=caller,
        )
    return _make


class TestBuildPlanFromLlm:
    async def test_success(self, engine, ctx_with_llm):
        ctx = ctx_with_llm()
        plan = await engine._build_plan_from_llm(ctx, "TEST", "generator")
        assert plan.source == "llm"
        assert plan.confidence == 0.40
        assert len(plan.actions) == 1
        assert plan.actions[0]["instruction"] == "Check relay"

    async def test_empty_response(self, engine, ctx_with_llm):
        ctx = ctx_with_llm(llm_return={"text": ""})
        plan = await engine._build_plan_from_llm(ctx, "TEST", "generator")
        assert plan.source == "error"
        assert plan.confidence == 0.0

    async def test_unparseable(self, engine, ctx_with_llm):
        ctx = ctx_with_llm(llm_return={"text": "Just some random text"})
        plan = await engine._build_plan_from_llm(ctx, "TEST", "generator")
        assert plan.source == "error"
        assert plan.confidence == 0.0

    async def test_timeout_exception(self, engine, ctx_with_llm):
        ctx = ctx_with_llm(llm_side_effect=asyncio.TimeoutError())
        plan = await engine._build_plan_from_llm(ctx, "TEST", "generator")
        assert plan.source == "error"
        assert plan.confidence == 0.0

    async def test_generic_exception(self, engine, ctx_with_llm):
        ctx = ctx_with_llm(llm_side_effect=RuntimeError("LLM down"))
        plan = await engine._build_plan_from_llm(ctx, "TEST", "generator")
        assert plan.source == "error"

    async def test_no_text_key(self, engine, ctx_with_llm):
        ctx = ctx_with_llm(llm_return={})
        plan = await engine._build_plan_from_llm(ctx, "TEST", "generator")
        assert plan.source == "error"
