"""Unit tests for SopEngine._safe_fallback."""
import pytest
from services.agent_sop_engine import ActionPlan, SopEngine, SopLookupContext

pytestmark = pytest.mark.unit


class TestSafeFallback:
    def test_returns_action_plan(self):
        ctx = SopLookupContext(incident_id=1, alarm_code="X", device_type="gen")
        result = SopEngine._safe_fallback(ctx, "X")
        assert isinstance(result, ActionPlan)

    def test_source_is_error(self):
        ctx = SopLookupContext(incident_id=1, alarm_code="X", device_type="gen")
        result = SopEngine._safe_fallback(ctx, "X")
        assert result.source == "error"

    def test_confidence_is_zero(self):
        ctx = SopLookupContext(incident_id=1, alarm_code="X", device_type="gen")
        result = SopEngine._safe_fallback(ctx, "X")
        assert result.confidence == 0.0

    def test_escalation_instruction(self):
        ctx = SopLookupContext(incident_id=1, alarm_code="X", device_type="gen")
        result = SopEngine._safe_fallback(ctx, "X")
        assert len(result.actions) == 1
        assert "Escalate" in result.actions[0]["instruction"]

    def test_device_fallback_when_no_name(self):
        ctx = SopLookupContext(
            incident_id=1, alarm_code="X", device_type="gen", device_name="",
        )
        result = SopEngine._safe_fallback(ctx, "X")
        assert result.device == "unknown"
