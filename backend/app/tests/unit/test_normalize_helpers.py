"""Unit tests for normalize_* helper functions."""
import pytest
from services.agent_sop_engine import (
    normalize_alarm_code,
    normalize_device_type,
    normalize_root_cause,
)

pytestmark = pytest.mark.unit


# ── normalize_alarm_code ──────────────────────────────────────────────

class TestNormalizeAlarmCode:
    def test_normal(self):
        assert normalize_alarm_code("shutdown") == "SHUTDOWN"

    def test_whitespace(self):
        assert normalize_alarm_code("  trip_stop  ") == "TRIP_STOP"

    def test_none(self):
        assert normalize_alarm_code(None) == "UNKNOWN"

    def test_empty(self):
        assert normalize_alarm_code("") == "UNKNOWN"

    def test_already_upper(self):
        assert normalize_alarm_code("CONN_LOST") == "CONN_LOST"


# ── normalize_device_type ─────────────────────────────────────────────

class TestNormalizeDeviceType:
    def test_normal(self):
        assert normalize_device_type("Generator") == "generator"

    def test_special_chars(self):
        result = normalize_device_type("Gas-Generator (v2)")
        assert result == "gasgeneratorv2"

    def test_none(self):
        assert normalize_device_type(None) == "unknown"

    def test_empty(self):
        assert normalize_device_type("") == "unknown"

    def test_only_special_chars(self):
        assert normalize_device_type("---") == "unknown"


# ── normalize_root_cause ──────────────────────────────────────────────

class TestNormalizeRootCause:
    def test_normal(self):
        assert normalize_root_cause("overheating") == "OVERHEATING"

    def test_none(self):
        assert normalize_root_cause(None) == "UNKNOWN"

    def test_empty(self):
        assert normalize_root_cause("") == "UNKNOWN"

    def test_whitespace_only(self):
        assert normalize_root_cause("   ") == "UNKNOWN"
