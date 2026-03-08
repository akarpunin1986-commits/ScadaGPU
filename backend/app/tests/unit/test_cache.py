"""Unit tests for SopEngine cache behavior."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from services.agent_sop_engine import SopEngine

pytestmark = pytest.mark.unit


class TestCache:
    async def test_hit_avoids_db_query(self, sop_engine):
        """Second lookup should use cache, not DB."""
        mock_result = AsyncMock(return_value=None)
        with patch.object(sop_engine, "_query_db", mock_result):
            await sop_engine._lookup("SHUTDOWN", "generator", "UNKNOWN")
            await sop_engine._lookup("SHUTDOWN", "generator", "UNKNOWN")
            assert mock_result.call_count == 1

    async def test_miss_queries_db(self, sop_engine):
        """First lookup should query DB."""
        mock_result = AsyncMock(return_value=None)
        with patch.object(sop_engine, "_query_db", mock_result):
            await sop_engine._lookup("SHUTDOWN", "generator", "UNKNOWN")
            mock_result.assert_called_once()

    async def test_cache_ttl_expires(self, sop_engine):
        """After TTL expires, cache should re-query DB."""
        mock_result = AsyncMock(return_value=None)
        monotonic_values = [100.0, 100.0, 300.0, 300.0]  # 200s gap > 120s TTL
        idx = 0

        def fake_monotonic():
            nonlocal idx
            val = monotonic_values[min(idx, len(monotonic_values) - 1)]
            idx += 1
            return val

        with patch.object(sop_engine, "_query_db", mock_result), \
             patch("services.agent_sop_engine.time.monotonic", side_effect=fake_monotonic):
            await sop_engine._lookup("X", "gen", "Y")
            await sop_engine._lookup("X", "gen", "Y")
            assert mock_result.call_count == 2

    async def test_stores_none_results(self, sop_engine):
        """Cache should store None to prevent repeated DB misses."""
        mock_result = AsyncMock(return_value=None)
        with patch.object(sop_engine, "_query_db", mock_result):
            result1 = await sop_engine._lookup("NONE", "x", "Y")
            result2 = await sop_engine._lookup("NONE", "x", "Y")
            assert result1 is None
            assert result2 is None
            assert mock_result.call_count == 1

    async def test_invalidate_cache_clears_all(self, sop_engine):
        """invalidate_cache should empty the cache dict."""
        sop_engine._cache["key1"] = (100.0, None)
        sop_engine._cache["key2"] = (100.0, None)
        sop_engine.invalidate_cache()
        assert len(sop_engine._cache) == 0

    async def test_cache_key_format(self, sop_engine):
        """Cache key should be alarm:device_type:cause."""
        mock_result = AsyncMock(return_value=None)
        with patch.object(sop_engine, "_query_db", mock_result):
            await sop_engine._lookup("SHUTDOWN", "generator", "FIRE")
            assert "SHUTDOWN:generator:FIRE" in sop_engine._cache

    async def test_different_keys_isolated(self, sop_engine):
        """Different lookup params should have independent cache entries."""
        mock_result = AsyncMock(return_value=None)
        with patch.object(sop_engine, "_query_db", mock_result):
            await sop_engine._lookup("A", "gen", "X")
            await sop_engine._lookup("B", "gen", "Y")
            assert mock_result.call_count == 2
            assert "A:gen:X" in sop_engine._cache
            assert "B:gen:Y" in sop_engine._cache

    async def test_double_checked_locking(self, sop_engine):
        """Concurrent lookups for same key should only query DB once."""
        call_count = 0

        async def slow_query(*args):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return None

        with patch.object(sop_engine, "_query_db", side_effect=slow_query):
            results = await asyncio.gather(
                sop_engine._lookup("SAME", "gen", "X"),
                sop_engine._lookup("SAME", "gen", "X"),
                sop_engine._lookup("SAME", "gen", "X"),
            )
            assert call_count == 1

    async def test_cache_repopulates_after_invalidation(self, sop_engine):
        """After invalidation, next lookup should re-query DB."""
        mock_result = AsyncMock(return_value=None)
        with patch.object(sop_engine, "_query_db", mock_result):
            await sop_engine._lookup("X", "gen", "Y")
            sop_engine.invalidate_cache()
            await sop_engine._lookup("X", "gen", "Y")
            assert mock_result.call_count == 2
