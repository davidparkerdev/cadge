"""Lightweight request metrics middleware.

Pushes request metrics to Observatory (fire-and-forget).
No local storage — Cadge is a dumb UI.
"""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.services.observatory_client import push_request_metric

# Paths to skip (health checks, SSE streams)
_SKIP_PATHS = frozenset({"/api/health", "/api/hooks/stream"})
_SKIP_PREFIXES = ("/api/sessions/", )  # SSE stream paths like /api/sessions/{id}/stream

SLOW_THRESHOLD_MS = 5000


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Skip noisy paths
        if path in _SKIP_PATHS:
            return await call_next(request)
        if any(path.startswith(p) and path.endswith("/stream") for p in _SKIP_PREFIXES):
            return await call_next(request)

        start = time.perf_counter()
        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - start) * 1000, 2)

            request_id = response.headers.get("X-Request-ID", uuid.uuid4().hex)
            slow = duration_ms > SLOW_THRESHOLD_MS

            push_request_metric(
                request_id=request_id,
                method=request.method,
                path=path,
                status_code=response.status_code,
                duration_ms=duration_ms,
                slow=slow,
            )
            return response
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            push_request_metric(
                request_id=uuid.uuid4().hex,
                method=request.method,
                path=path,
                status_code=500,
                duration_ms=duration_ms,
                slow=duration_ms > SLOW_THRESHOLD_MS,
            )
            raise
