"""Supabase JWT verification dependency (JWKS / RS256)."""

from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from api.settings import BackendSettings, get_settings

_bearer = HTTPBearer(auto_error=True)


class User(BaseModel):
    """Authenticated user extracted from a verified JWT."""

    id: str = Field(description="Supabase user id (JWT sub claim).")
    email: str | None = Field(default=None, description="User email when present in the token.")


@lru_cache(maxsize=1)
def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    """Return a cached JWKS client for the given URL."""
    return jwt.PyJWKClient(jwks_url)


def current_user(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    settings: Annotated[BackendSettings, Depends(get_settings)],
) -> User:
    """Verify the Bearer JWT against Supabase JWKS and return the user.

    Raises:
        HTTPException: 401 if the token is missing/invalid/expired.
    """
    token = creds.credentials
    jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
    try:
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=settings.supabase_jwt_aud,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
    return User(id=claims["sub"], email=claims.get("email"))
