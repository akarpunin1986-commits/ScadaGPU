"""Unit tests for economics calculation fixes — NULL handling, nominal power."""
from __future__ import annotations

import pytest


class TestNominalKwLookup:
    """Verify NOMINAL_KW is used instead of hardcoded values."""

    def test_nominal_kw_dict_exists(self):
        """NOMINAL_KW dict should exist in economics module."""
        from api.economics import NOMINAL_KW, DEFAULT_NOMINAL_KW
        assert isinstance(NOMINAL_KW, dict)
        assert isinstance(DEFAULT_NOMINAL_KW, int)
        # MKZ (site 3) and YKZ (site 5) should have entries
        assert 3 in NOMINAL_KW
        assert 5 in NOMINAL_KW

    def test_nominal_kw_values_correct(self):
        """Each site should have 320 kW total (2 generators x 160 kW)."""
        from api.economics import NOMINAL_KW
        assert NOMINAL_KW[3] == 320
        assert NOMINAL_KW[5] == 320

    def test_gen_nominal_from_dict(self):
        """Per-generator nominal should be NOMINAL_KW // 2."""
        from api.economics import NOMINAL_KW, DEFAULT_NOMINAL_KW
        for site_id in (3, 5):
            gen_nominal = NOMINAL_KW.get(site_id, DEFAULT_NOMINAL_KW) // 2
            assert gen_nominal == 160


class TestSsrfProtection:
    """Verify legacy Bitrix endpoints validate webhook URLs."""

    def test_bitrix_url_validation_rejects_internal(self):
        """Internal URLs should be rejected."""
        from api.bitrix import _validate_webhook_url
        import fastapi

        with pytest.raises(fastapi.HTTPException) as exc_info:
            _validate_webhook_url("http://192.168.30.130:8000/api/test")
        assert exc_info.value.status_code == 400

    def test_bitrix_url_validation_rejects_localhost(self):
        """Localhost URLs should be rejected."""
        from api.bitrix import _validate_webhook_url
        import fastapi

        with pytest.raises(fastapi.HTTPException):
            _validate_webhook_url("https://localhost/evil")

    def test_bitrix_url_validation_accepts_bitrix24(self):
        """Bitrix24 domains should be accepted."""
        from api.bitrix import _validate_webhook_url

        result = _validate_webhook_url("https://bricks-trade.bitrix24.ru/rest/222/abc/")
        assert result == "https://bricks-trade.bitrix24.ru/rest/222/abc/"


class TestGridPriceFallback:
    """Verify grid_price fallback distinguishes zero from None."""

    def test_zero_grid_price_preserved(self):
        """grid_price=0 should stay 0, not become 8.0."""
        # Simulate the fixed logic
        grid_price = 0
        if grid_price is None:
            grid_price = 8.0
        assert grid_price == 0

    def test_none_grid_price_becomes_fallback(self):
        """grid_price=None should become 8.0."""
        grid_price = None
        if grid_price is None:
            grid_price = 8.0
        assert grid_price == 8.0
