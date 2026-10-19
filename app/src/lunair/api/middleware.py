"""ASGI middleware for the core."""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a correlation id to every request and response.

    Honours an inbound ``X-Request-Id`` (so a client can supply its own) and
    otherwise generates one. The id is stored on ``request.state`` and echoed
    on the response so gateway, core and provider logs can be joined.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex[:16]}"
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response
