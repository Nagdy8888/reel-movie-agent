"""Rate-limit key contract tests."""

from fastapi import Request

from api.limiter import get_authenticated_user_id


def test_authenticated_user_limit_key_is_independent_of_ip() -> None:
    """The user limiter reads the verified JWT subject bound to request state."""
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/chat",
            "headers": [],
            "client": ("203.0.113.10", 1234),
        }
    )
    request.state.user_id = "user-123"

    assert get_authenticated_user_id(request) == "user:user-123"
