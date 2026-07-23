"""Unit tests for Supabase JWT verification."""

from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials

from api.auth import current_user
from api.settings import BackendSettings


def _request() -> Request:
    """Build a minimal Starlette request for direct dependency tests."""
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


def _credentials() -> HTTPAuthorizationCredentials:
    """Return fixed bearer credentials for JWT verifier tests."""
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="encoded.jwt")


def _settings() -> BackendSettings:
    """Return auth settings that do not depend on the developer environment."""
    return BackendSettings(
        app_env="dev",
        supabase_url="https://project.supabase.co",
        supabase_jwt_aud="authenticated",
    )


def test_current_user_accepts_valid_token_and_binds_request_state() -> None:
    """A verified token returns its subject and exposes it to middleware/limits."""
    request = _request()
    signing_key = MagicMock()
    signing_key.key = object()
    jwks = MagicMock()
    jwks.get_signing_key_from_jwt.return_value = signing_key

    with (
        patch("api.auth._jwks_client", return_value=jwks),
        patch(
            "api.auth.jwt.decode",
            return_value={"sub": "user-1", "email": "user@example.com"},
        ) as decode,
    ):
        user = current_user(request, _credentials(), _settings())

    assert user.id == "user-1"
    assert user.email == "user@example.com"
    assert request.state.user_id == "user-1"
    decode.assert_called_once_with(
        "encoded.jwt",
        signing_key.key,
        algorithms=["RS256", "ES256"],
        audience="authenticated",
    )


@pytest.mark.parametrize(
    "error",
    [
        jwt.ExpiredSignatureError("expired"),
        jwt.InvalidSignatureError("tampered"),
        jwt.InvalidAudienceError("wrong audience"),
    ],
)
def test_current_user_rejects_invalid_jwt(error: jwt.PyJWTError) -> None:
    """Expired, tampered, and wrong-audience tokens all produce a generic 401."""
    signing_key = MagicMock()
    signing_key.key = object()
    jwks = MagicMock()
    jwks.get_signing_key_from_jwt.return_value = signing_key

    with (
        patch("api.auth._jwks_client", return_value=jwks),
        patch("api.auth.jwt.decode", side_effect=error),
        pytest.raises(HTTPException) as raised,
    ):
        current_user(_request(), _credentials(), _settings())

    assert raised.value.status_code == 401
    assert raised.value.detail == "Invalid token"


def test_current_user_rejects_jwks_failure() -> None:
    """A JWKS retrieval or key-selection failure produces a generic 401."""
    jwks = MagicMock()
    jwks.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientError("jwks unavailable")

    with (
        patch("api.auth._jwks_client", return_value=jwks),
        pytest.raises(HTTPException) as raised,
    ):
        current_user(_request(), _credentials(), _settings())

    assert raised.value.status_code == 401
    assert raised.value.detail == "Invalid token"


def test_current_user_rejects_missing_subject() -> None:
    """A cryptographically valid JWT without a subject is still unauthorized."""
    signing_key = MagicMock()
    signing_key.key = object()
    jwks = MagicMock()
    jwks.get_signing_key_from_jwt.return_value = signing_key

    with (
        patch("api.auth._jwks_client", return_value=jwks),
        patch("api.auth.jwt.decode", return_value={"email": "user@example.com"}),
        pytest.raises(HTTPException) as raised,
    ):
        current_user(_request(), _credentials(), _settings())

    assert raised.value.status_code == 401
