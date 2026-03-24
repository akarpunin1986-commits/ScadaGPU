"""Unit tests for SopEngine._build_fallback_prompt."""
import pytest
from services.agent_sop_engine import SopEngine

pytestmark = pytest.mark.unit


class TestBuildFallbackPrompt:
    def test_contains_alarm(self):
        prompt = SopEngine._build_fallback_prompt("SHUTDOWN", "generator", "overheating", "Gen1")
        assert "SHUTDOWN" in prompt

    def test_contains_device(self):
        prompt = SopEngine._build_fallback_prompt("X", "generator", "Y", "My Generator")
        assert "My Generator" in prompt

    def test_contains_cause(self):
        prompt = SopEngine._build_fallback_prompt("X", "gen", "overheating", "Gen1")
        assert "overheating" in prompt

    def test_json_format_instruction(self):
        prompt = SopEngine._build_fallback_prompt("X", "gen", "Y", "G")
        assert "JSON array" in prompt

    def test_max_steps_instruction(self):
        prompt = SopEngine._build_fallback_prompt("X", "gen", "Y", "G")
        assert "Maximum 10 steps" in prompt
