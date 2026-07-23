"""Shared slowapi limiter."""

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def get_authenticated_user_id(request: Request) -> str:
    """Return a namespaced rate-limit key for the authenticated user."""
    user_id = getattr(request.state, "user_id", None)
    return f"user:{user_id}" if user_id else "user:anonymous"


limiter = Limiter(key_func=get_remote_address)
