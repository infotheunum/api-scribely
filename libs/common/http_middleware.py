from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from common.tracing import TRACE_ID_HEADER, new_trace_id, set_trace_id


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Reads X-Trace-Id from the incoming request (or mints one), exposes
    it via get_trace_id() for the duration of the request, and echoes it
    back on the response. Used by api/worker only — rewrite is gRPC-only
    and uses the interceptors in grpc_interceptors.py instead."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        trace_id = request.headers.get(TRACE_ID_HEADER) or new_trace_id()
        set_trace_id(trace_id)
        response = await call_next(request)
        response.headers[TRACE_ID_HEADER] = trace_id
        return response
