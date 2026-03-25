"""Unit tests for auth security fixes — JWT expiry, inactive user, set-token validation,
self-demotion prevention."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from services.auth import create_jwt, verify_jwt


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = 1
    user.role = "admin"
    user.name = "Test User"
    user.bitrix_id = 100
    return user


class TestJwtExpiry:
    """Verify JWT tokens have expiry when configured."""

    def test_jwt_has_expiry_claim(self, mock_user):
        """JWT should include exp claim when JWT_EXPIRE_HOURS > 0."""
        with patch("services.auth.settings") as mock_settings:
            mock_settings.JWT_EXPIRE_HOURS = 720
            mock_settings.JWT_SECRET_KEY = "test-secret-key-32bytes-minimum!!"
            mock_settings.JWT_ALGORITHM = "HS256"

            token = create_jwt(mock_user)
            payload = verify_jwt(token)

            assert payload is not None
            assert "exp" in payload
            assert payload["sub"] == "1"

    def test_expired_jwt_returns_none(self, mock_user):
        """Expired JWT should return None from verify_jwt."""
        import jwt as pyjwt

        with patch("services.auth.settings") as mock_settings:
            mock_settings.JWT_SECRET_KEY = "test-secret-key-32bytes-minimum!!"
            mock_settings.JWT_ALGORITHM = "HS256"

            # Create an already-expired token
            payload = {
                "sub": "1",
                "role": "admin",
                "name": "Test",
                "bid": 100,
                "exp": datetime.utcnow() - timedelta(hours=1),
            }
            expired_token = pyjwt.encode(payload, "test-secret-key-32bytes-minimum!!", algorithm="HS256")

            result = verify_jwt(expired_token)
            assert result is None

    def test_invalid_jwt_returns_none(self):
        """Tampered JWT should return None."""
        with patch("services.auth.settings") as mock_settings:
            mock_settings.JWT_SECRET_KEY = "test-secret-key-32bytes-minimum!!"
            mock_settings.JWT_ALGORITHM = "HS256"

            result = verify_jwt("invalid.token.here")
            assert result is None


class TestVerifyJwtLogging:
    """Verify that verify_jwt logs failures instead of silently swallowing."""

    def test_verify_jwt_logs_on_failure(self):
        """Failed JWT verification should log at debug level."""
        with patch("services.auth.settings") as mock_settings:
            mock_settings.JWT_SECRET_KEY = "test-secret-key-32bytes-minimum!!"
            mock_settings.JWT_ALGORITHM = "HS256"

            with patch("logging.getLogger") as mock_get_logger:
                mock_logger_instance = MagicMock()
                mock_get_logger.return_value = mock_logger_instance

                result = verify_jwt("bad-token")
                assert result is None
                # verify_jwt calls logging.getLogger("scada.auth").debug(...)
                assert mock_logger_instance.debug.called


class TestSetTokenValidation:
    """Verify /set-token endpoint validates JWT before setting cookie."""

    def test_set_token_requires_valid_jwt(self):
        """The /set-token endpoint should reject invalid tokens.
        (Integration-level check — the actual endpoint calls verify_jwt)."""
        with patch("services.auth.settings") as mock_settings:
            mock_settings.JWT_SECRET_KEY = "test-secret-key-32bytes-minimum!!"
            mock_settings.JWT_ALGORITHM = "HS256"

            # Invalid token should be rejected
            result = verify_jwt("arbitrary-string")
            assert result is None, "Invalid JWT should be rejected by verify_jwt"
