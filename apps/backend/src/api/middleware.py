"""Cross-cutting middleware: request-id, security headers, structured logging."""

import hashlib
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("reel.access")

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "Cache-Control": "no-store",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id, set security headers, and log each request."""

    async def dispatch(self, request: Request, call_next):
        """Process one request with a bound request id and security headers."""
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        response.headers.update(_SECURITY_HEADERS)
        response.headers["X-Request-ID"] = request_id
        user_id = getattr(request.state, "user_id", None)
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": round((time.perf_counter() - start) * 1000, 1),
                "user_ref": (
                    hashlib.sha256(user_id.encode()).hexdigest()[:12] if user_id else None
                ),
            },
        )
        return response
