"""Unit tests for SopEngine._build_plan_from_db."""
import pytest
from services.agent_sop_engine import SopEngine, SopLookupContext

pytestmark = pytest.mark.unit


@pytest.fixture
def engine(session_factory):
    return SopEngine(session_factory)


@pytest.fixture
def ctx():
    return SopLookupContext(
        incident_id=1,
        alarm_code="SHUTDOWN",
        device_type="generator",
        device_name="Generator 1",
        severity="critical",
        cause="overheating",
    )


class TestBuildPlanFromDb:
    def test_tier1_confidence_095(self, engine, ctx, mock_sop_procedure):
        sop = mock_sop_procedure(root_cause="OVERHEATING", device_type="generator")
        plan = engine._build_plan_from_db(ctx, sop, "generator", "OVERHEATING")
        assert plan.confidence == 0.95

    def test_tier2_confidence_070(self, engine, ctx, mock_sop_procedure):
        sop = mock_sop_procedure(root_cause=None, device_type="generator")
        plan = engine._build_plan_from_db(ctx, sop, "generator", "UNKNOWN")
        assert plan.confidence == 0.70

    def test_tier3_confidence_050(self, engine, ctx, mock_sop_procedure):
        sop = mock_sop_procedure(root_cause=None, device_type="any")
        plan = engine._build_plan_from_db(ctx, sop, "any", "UNKNOWN")
        assert plan.confidence == 0.50

    def test_actions_parsed(self, engine, ctx, mock_sop_procedure):
        sop = mock_sop_procedure(actions_json=[
            {"step": 1, "instruction": "Do A"},
            {"step": 2, "instruction": "Do B"},
        ])
        plan = engine._build_plan_from_db(ctx, sop, "generator", "X")
        assert len(plan.actions) == 2
        assert plan.actions[0]["instruction"] == "Do A"
        assert plan.actions[1]["instruction"] == "Do B"

    def test_max_20_actions(self, engine, ctx, mock_sop_procedure):
        sop = mock_sop_procedure(
            actions_json=[{"step": i, "instruction": f"Step {i}"} for i in range(1, 30)]
        )
        plan = engine._build_plan_from_db(ctx, sop, "generator", "X")
        assert len(plan.actions) == 20

    def test_instruction_truncated(self, engine, ctx, mock_sop_procedure):
        sop = mock_sop_procedure(actions_json=[
            {"step": 1, "instruction": "A" * 600}
        ])
        plan = engine._build_plan_from_db(ctx, sop, "generator", "X")
        assert len(plan.actions[0]["instruction"]) == 500

    def test_optional_fields_copied(self, engine, ctx, mock_sop_procedure):
        sop = mock_sop_procedure(actions_json=[{
            "step": 1,
            "instruction": "Test",
            "ui_control": "path/ctrl",
            "expected_state": "OK",
            "verification": "Check it",
            "safety_note": "Be safe",
        }])
        plan = engine._build_plan_from_db(ctx, sop, "generator", "X")
        action = plan.actions[0]
        assert action["ui_control"] == "path/ctrl"
        assert action["safety_note"] == "Be safe"

    def test_optional_fields_truncated(self, engine, ctx, mock_sop_procedure):
        sop = mock_sop_procedure(actions_json=[{
            "step": 1,
            "instruction": "Test",
            "safety_note": "X" * 600,
        }])
        plan = engine._build_plan_from_db(ctx, sop, "generator", "X")
        assert len(plan.actions[0]["safety_note"]) == 500

    def test_non_dict_actions_skipped(self, engine, ctx, mock_sop_procedure):
        sop = mock_sop_procedure(actions_json=[
            "not a dict",
            42,
            {"step": 1, "instruction": "Valid"},
        ])
        plan = engine._build_plan_from_db(ctx, sop, "generator", "X")
        assert len(plan.actions) == 1
        assert plan.actions[0]["instruction"] == "Valid"

    def test_empty_actions(self, engine, ctx, mock_sop_procedure):
        sop = mock_sop_procedure(actions_json=[])
        plan = engine._build_plan_from_db(ctx, sop, "generator", "X")
        assert plan.actions == []

    def test_null_actions(self, engine, ctx, mock_sop_procedure):
        sop = mock_sop_procedure(actions_json=None)
        plan = engine._build_plan_from_db(ctx, sop, "generator", "X")
        assert plan.actions == []

    def test_device_name_precedence(self, engine, mock_sop_procedure):
        ctx_with_name = SopLookupContext(
            incident_id=1, alarm_code="X", device_type="gen",
            device_name="My Generator",
        )
        sop = mock_sop_procedure()
        plan = engine._build_plan_from_db(ctx_with_name, sop, "gen", "X")
        assert plan.device == "My Generator"

        ctx_no_name = SopLookupContext(
            incident_id=1, alarm_code="X", device_type="gen",
            device_name="",
        )
        plan = engine._build_plan_from_db(ctx_no_name, sop, "gen", "X")
        assert plan.device == "gen"

    def test_sop_id_and_version(self, engine, ctx, mock_sop_procedure):
        sop = mock_sop_procedure(id=42, version=3)
        plan = engine._build_plan_from_db(ctx, sop, "generator", "X")
        assert plan.sop_id == 42
        assert plan.sop_version == 3
