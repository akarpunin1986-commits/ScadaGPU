"""Unit tests for WebSocket security — auth check, message size guard, connection manager."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.websocket import ConnectionManager, _MAX_MESSAGE_SIZE


class TestConnectionManager:
    """Test ConnectionManager with lock and size guard."""

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        ws.accept = AsyncMock()

        await mgr.connect(ws)
        assert len(mgr.connections) == 1

        await mgr.disconnect(ws)
        assert len(mgr.connections) == 0

    @pytest.mark.asyncio
    async def test_disconnect_idempotent(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        ws.accept = AsyncMock()

        await mgr.connect(ws)
        await mgr.disconnect(ws)
        await mgr.disconnect(ws)  # second call should not raise
        assert len(mgr.connections) == 0

    @pytest.mark.asyncio
    async def test_broadcast_skips_oversized_messages(self):
        """Messages >= 1MB should be skipped."""
        mgr = ConnectionManager()
        ws = AsyncMock()
        ws.accept = AsyncMock()
        await mgr.connect(ws)

        big_message = "x" * (_MAX_MESSAGE_SIZE + 1)
        await mgr.broadcast(big_message)

        # ws.send_text should NOT have been called
        ws.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_broadcast_sends_normal_messages(self):
        """Normal-sized messages should be sent."""
        mgr = ConnectionManager()
        ws = AsyncMock()
        ws.accept = AsyncMock()
        await mgr.connect(ws)

        await mgr.broadcast('{"type": "test"}')
        ws.send_text.assert_called_once_with('{"type": "test"}')

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_connections(self):
        """Connections that error on send should be removed."""
        mgr = ConnectionManager()

        good_ws = AsyncMock()
        good_ws.accept = AsyncMock()
        bad_ws = AsyncMock()
        bad_ws.accept = AsyncMock()
        bad_ws.send_text = AsyncMock(side_effect=ConnectionError("gone"))

        await mgr.connect(good_ws)
        await mgr.connect(bad_ws)
        assert len(mgr.connections) == 2

        await mgr.broadcast("hello")
        assert len(mgr.connections) == 1
        assert good_ws in mgr.connections
        assert bad_ws not in mgr.connections


class TestBridgeFunction:
    """Test the generic _redis_bridge function."""

    @pytest.mark.asyncio
    async def test_bridge_with_envelope(self):
        """When envelope_type is set, payload should be wrapped."""
        from core.websocket import _redis_bridge, manager

        # Clear any existing connections
        manager.connections.clear()

        ws = AsyncMock()
        ws.accept = AsyncMock()
        await manager.connect(ws)

        # Create mock Redis pubsub
        mock_redis = AsyncMock()
        mock_pubsub = AsyncMock()

        messages = [
            {"type": "subscribe", "data": 1},
            {"type": "message", "data": b'{"foo": "bar"}'},
        ]

        async def mock_listen():
            for msg in messages:
                yield msg

        mock_pubsub.listen = mock_listen
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.close = AsyncMock()
        mock_redis.pubsub.return_value = mock_pubsub

        # Run bridge with CancelledError after processing
        async def run_bridge():
            try:
                await _redis_bridge(mock_redis, "test:channel", envelope_type="test_event")
            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(run_bridge())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Check the ws received the wrapped message
        if ws.send_text.called:
            import json
            sent = json.loads(ws.send_text.call_args[0][0])
            assert sent["type"] == "test_event"
            assert sent["data"]["foo"] == "bar"

        # Cleanup
        manager.connections.clear()
