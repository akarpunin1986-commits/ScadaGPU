"""Unit tests for SopEngine._parse_llm_actions static method."""
import json

import pytest
from services.agent_sop_engine import SopEngine

pytestmark = pytest.mark.unit

parse = SopEngine._parse_llm_actions


class TestParseLlmActions:
    def test_valid_json_array(self):
        raw = '[{"step": 1, "instruction": "Check relay status"}]'
        result = parse(raw)
        assert len(result) == 1
        assert result[0]["step"] == 1
        assert result[0]["instruction"] == "Check relay status"

    def test_with_markdown_fences(self):
        raw = '```json\n[{"step": 1, "instruction": "Do it"}]\n```'
        result = parse(raw)
        assert len(result) == 1
        assert result[0]["instruction"] == "Do it"

    def test_with_leading_text(self):
        raw = 'Here are the steps:\n[{"step": 1, "instruction": "Step one"}]'
        result = parse(raw)
        assert len(result) == 1

    def test_empty_string(self):
        assert parse("") == []

    def test_none_falsy(self):
        assert parse("") == []

    def test_invalid_json(self):
        assert parse("[{bad json}]") == []

    def test_no_array(self):
        assert parse("No JSON array here at all.") == []

    def test_empty_array(self):
        assert parse("[]") == []

    def test_non_dict_items(self):
        raw = '[1, "two", 3]'
        assert parse(raw) == []

    def test_missing_instruction(self):
        raw = '[{"step": 1}]'
        assert parse(raw) == []

    def test_empty_instruction(self):
        raw = '[{"step": 1, "instruction": ""}]'
        assert parse(raw) == []

    def test_instruction_truncated(self):
        long_instruction = "A" * 600
        raw = json.dumps([{"step": 1, "instruction": long_instruction}])
        result = parse(raw)
        assert len(result[0]["instruction"]) == 500

    def test_max_actions_limit(self):
        actions = [{"step": i, "instruction": f"Step {i}"} for i in range(1, 26)]
        raw = json.dumps(actions)
        result = parse(raw)
        assert len(result) == 20

    def test_optional_fields_preserved(self):
        raw = json.dumps([{
            "step": 1,
            "instruction": "Check",
            "ui_control": "path/to/control",
            "expected_state": "OK",
            "verification": "Verify it",
            "safety_note": "Be careful",
        }])
        result = parse(raw)
        assert result[0]["ui_control"] == "path/to/control"
        assert result[0]["expected_state"] == "OK"
        assert result[0]["verification"] == "Verify it"
        assert result[0]["safety_note"] == "Be careful"

    def test_optional_fields_truncated(self):
        raw = json.dumps([{
            "step": 1,
            "instruction": "X",
            "safety_note": "B" * 600,
        }])
        result = parse(raw)
        assert len(result[0]["safety_note"]) == 500

    def test_optional_field_non_string_excluded(self):
        raw = json.dumps([{
            "step": 1,
            "instruction": "X",
            "safety_note": 123,
        }])
        result = parse(raw)
        assert "safety_note" not in result[0]

    def test_input_truncated_at_4000(self):
        """Input > 4000 chars is truncated before parsing."""
        valid_action = json.dumps([{"step": 1, "instruction": "OK"}])
        # Place valid JSON at position > 4000 — it should NOT be found
        raw = "x" * 4100 + valid_action
        assert parse(raw) == []

    def test_step_defaults_to_index(self):
        raw = json.dumps([
            {"instruction": "First"},
            {"instruction": "Second"},
        ])
        result = parse(raw)
        assert result[0]["step"] == 1
        assert result[1]["step"] == 2

    def test_multiple_code_fences(self):
        raw = '```\nsome text\n```\n```json\n[{"step": 1, "instruction": "OK"}]\n```'
        result = parse(raw)
        assert len(result) == 1
