"""Safety validation tests for SOP Engine."""
import json

import pytest
from services.agent_sop_engine import ActionPlan, SopEngine, SopLookupContext
from tests.conftest import SEED_PROCEDURES

pytestmark = pytest.mark.safety

DANGEROUS_KEYWORDS = [
    "bypass safety",
    "disable protection",
    "override interlock",
    "ignore alarm",
    "skip verification",
    "force start",
]


class TestSafety:
    def test_seed_sops_have_safety_notes(self):
        """Every seed SOP should have at least one action with a safety_note."""
        for proc in SEED_PROCEDURES:
            safety_notes = [
                a.get("safety_note")
                for a in proc["actions_json"]
                if a.get("safety_note")
            ]
            assert len(safety_notes) > 0, (
                f"SOP {proc['alarm_code']}/{proc['device_type']} has no safety_notes"
            )

    def test_safety_note_preserved_in_plan(self, mock_sop_procedure):
        """safety_note from SOP should appear in ActionPlan output."""
        sop = mock_sop_procedure(actions_json=[{
            "step": 1,
            "instruction": "Check relay",
            "safety_note": "Wear protective gear",
        }])
        engine = SopEngine.__new__(SopEngine)
        ctx = SopLookupContext(incident_id=1, alarm_code="X", device_type="gen")
        plan = engine._build_plan_from_db(ctx, sop, "gen", "X")
        assert plan.actions[0]["safety_note"] == "Wear protective gear"

    def test_no_dangerous_instructions_in_seed_sops(self):
        """Seed SOPs must not contain dangerous keywords."""
        for proc in SEED_PROCEDURES:
            for action in proc["actions_json"]:
                instruction = action.get("instruction", "").lower()
                for keyword in DANGEROUS_KEYWORDS:
                    assert keyword not in instruction, (
                        f"Dangerous keyword '{keyword}' found in "
                        f"{proc['alarm_code']} step {action.get('step')}"
                    )

    def test_escalation_when_no_sop(self):
        """When no SOP found, fallback must include escalation."""
        ctx = SopLookupContext(incident_id=1, alarm_code="X", device_type="gen")
        plan = SopEngine._safe_fallback(ctx, "X")
        assert any("Escalate" in a["instruction"] for a in plan.actions)

    def test_llm_actions_cannot_bypass_max_limits(self):
        """Even with 50 LLM actions, max 20 are included."""
        actions = [{"step": i, "instruction": f"Step {i}"} for i in range(1, 51)]
        raw = json.dumps(actions)
        result = SopEngine._parse_llm_actions(raw)
        assert len(result) <= 20

    def test_llm_instruction_length_capped(self):
        """LLM instruction > 500 chars is truncated."""
        raw = json.dumps([{"step": 1, "instruction": "X" * 1000}])
        result = SopEngine._parse_llm_actions(raw)
        assert len(result[0]["instruction"]) == 500

    def test_action_plan_json_size_capped(self):
        """ActionPlan with huge data is truncated in to_dict()."""
        big_actions = [{"step": i, "instruction": "X" * 500} for i in range(1, 30)]
        plan = ActionPlan(
            incident_id=1, device="Gen", alarm="X", cause="Y",
            actions=big_actions,
        )
        d = plan.to_dict()
        assert len(d["actions"]) <= 5
        assert d.get("_truncated") is True

    def test_safe_fallback_is_deterministic(self):
        """_safe_fallback always returns the same structure."""
        ctx1 = SopLookupContext(incident_id=1, alarm_code="A", device_type="x")
        ctx2 = SopLookupContext(incident_id=2, alarm_code="B", device_type="y")
        plan1 = SopEngine._safe_fallback(ctx1, "A")
        plan2 = SopEngine._safe_fallback(ctx2, "B")
        assert plan1.source == plan2.source == "error"
        assert plan1.confidence == plan2.confidence == 0.0
        assert len(plan1.actions) == len(plan2.actions) == 1
