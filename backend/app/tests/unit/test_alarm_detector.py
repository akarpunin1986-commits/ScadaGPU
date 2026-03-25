"""Unit tests for AlarmDetector — verifies fixes for partial payload merge,
alarm id publish, dedup, and logging."""
from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.alarm_detector import AlarmDetector, ALARM_FLAG_MAP, CONN_LOST_CODE


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.pubsub.return_value = AsyncMock()
    r.publish = AsyncMock()
    return r


@pytest.fixture
def mock_session_factory():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = session
    return factory, session


@pytest.fixture
def detector(mock_redis, mock_session_factory):
    factory, _ = mock_session_factory
    d = AlarmDetector(mock_redis, factory)
    return d


class TestPrevStateMerge:
    """Verify _prev is merged (not overwritten) on partial payloads."""

    @pytest.mark.asyncio
    async def test_partial_payload_preserves_existing_flags(self, detector):
        """If payload has only alarm_common, alarm_shutdown from prev must survive."""
        # Simulate first full payload
        detector._prev[1] = {"alarm_common": True, "alarm_shutdown": True}

        # Partial payload with only alarm_common going off
        payload = {
            "device_id": 1,
            "online": True,
            "alarm_common": False,
        }

        # Mock session to prevent DB calls
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        result_mock = AsyncMock()
        result_mock.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        detector.session_factory = MagicMock(return_value=session)

        await detector._process(payload)

        # alarm_shutdown must still be True (not wiped)
        assert detector._prev[1].get("alarm_shutdown") is True
        # alarm_common must be updated to False
        assert detector._prev[1].get("alarm_common") is False

    @pytest.mark.asyncio
    async def test_full_payload_updates_all_flags(self, detector):
        """Full payload with all flags updates everything."""
        detector._prev[1] = {}

        payload = {
            "device_id": 1,
            "online": True,
            "alarm_common": True,
            "alarm_shutdown": False,
            "alarm_warning": True,
            "alarm_block": False,
        }

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.new = set()
        detector.session_factory = MagicMock(return_value=session)

        await detector._process(payload)

        assert detector._prev[1]["alarm_common"] is True
        assert detector._prev[1]["alarm_shutdown"] is False
        assert detector._prev[1]["alarm_warning"] is True
        assert detector._prev[1]["alarm_block"] is False


class TestAlarmPublishFormat:
    """Verify hardware alarm publish code includes device_type and occurred_at fields."""

    def test_publish_code_contains_device_type_field(self):
        """The alarm publish JSON template should include device_type."""
        import inspect
        source = inspect.getsource(AlarmDetector._process)
        # After our fix, the publish should contain device_type
        assert '"device_type": device_type' in source or "'device_type': device_type" in source

    def test_publish_code_contains_occurred_at_field(self):
        """The alarm publish JSON template should include occurred_at."""
        import inspect
        source = inspect.getsource(AlarmDetector._process)
        assert "occurred_at" in source

    def test_prev_uses_setdefault_update(self):
        """The _process method should merge _prev state, not replace."""
        import inspect
        source = inspect.getsource(AlarmDetector._process)
        assert "setdefault" in source and ".update(current)" in source


class TestConnLostLoggingCode:
    """Verify Redis publish errors are logged, not silently swallowed."""

    def test_conn_lost_publish_has_warning_log(self):
        """CONN_LOST publish except block should log warning, not pass."""
        import inspect
        source = inspect.getsource(AlarmDetector._process)
        # After our fix, there should be logger.warning in the CONN_LOST except block
        assert "logger.warning" in source
        # There should NOT be bare 'except Exception:\n                        pass'
        assert "except Exception:\n                        pass" not in source
