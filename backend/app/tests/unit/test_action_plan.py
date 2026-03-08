"""Unit tests for ActionPlan dataclass."""
import json

import pytest
from services.agent_sop_engine import ActionPlan

pytestmark = pytest.mark.unit


class TestActionPlan:
    def test_defaults(self):
        plan = ActionPlan(incident_id=1, device="Gen1", alarm="SHUTDOWN", cause="test")
        assert plan.actions == []
        assert plan.source == "db"
        assert plan.confidence == 0.0
        assert plan.sop_id is None
        assert plan.sop_version is None

    def test_to_dict_basic(self):
        plan = ActionPlan(
            incident_id=1, device="Gen1", alarm="SHUTDOWN", cause="test",
            actions=[{"step": 1, "instruction": "Do something"}],
            source="db", confidence=0.95, sop_id=42, sop_version=2,
        )
        d = plan.to_dict()
        assert d["incident_id"] == 1
        assert d["device"] == "Gen1"
        assert d["alarm"] == "SHUTDOWN"
        assert d["cause"] == "test"
        assert len(d["actions"]) == 1
        assert d["source"] == "db"
        assert d["confidence"] == 0.95
        assert d["sop_id"] == 42
        assert d["sop_version"] == 2

    def test_to_dict_serializable(self):
        plan = ActionPlan(
            incident_id=1, device="Gen1", alarm="X", cause="Y",
            actions=[{"step": 1, "instruction": "test"}],
        )
        serialized = json.dumps(plan.to_dict())
        assert isinstance(serialized, str)

    def test_to_dict_truncation_over_10kb(self):
        """When serialized JSON > 10240 bytes, truncate to 5 actions."""
        big_actions = [
            {"step": i, "instruction": "A" * 500}
            for i in range(1, 30)
        ]
        plan = ActionPlan(
            incident_id=1, device="Gen1", alarm="X", cause="Y",
            actions=big_actions,
        )
        d = plan.to_dict()
        assert len(d["actions"]) == 5
        assert d["_truncated"] is True

    def test_to_dict_under_limit(self):
        plan = ActionPlan(
            incident_id=1, device="Gen1", alarm="X", cause="Y",
            actions=[{"step": 1, "instruction": "Short"}],
        )
        d = plan.to_dict()
        assert "_truncated" not in d

    def test_to_dict_empty_actions_no_truncation(self):
        plan = ActionPlan(incident_id=1, device="Gen1", alarm="X", cause="Y")
        d = plan.to_dict()
        assert d["actions"] == []
        assert "_truncated" not in d
