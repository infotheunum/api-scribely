from __future__ import annotations

import uuid
from contextvars import ContextVar

# Sits in every log line and follows a material through the whole pipeline:
# RawItem -> NewsCluster -> Draft -> PublishRecord (ТЗ §4.20). Introduced in
# Phase 0 on purpose, not bolted on later.
#
# No web-framework import here on purpose: this module is used by rewrite
# (gRPC-only, no HTTP dependency at all — ТЗ §6.6) via grpc_interceptors.py,
# not just by api/worker. The Starlette-based TraceIdMiddleware lives in
# common/http_middleware.py instead, so rewrite's image never needs
# starlette/fastapi installed.
TRACE_ID_HEADER = "X-Trace-Id"
TRACE_ID_METADATA_KEY = "x-trace-id"

_trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)


def new_trace_id() -> str:
    return uuid.uuid4().hex


def get_trace_id() -> str:
    """Returns the trace_id for the current request/call context, minting
    one if none has been set yet (e.g. a scheduler-initiated job)."""
    trace_id = _trace_id_var.get()
    if trace_id is None:
        trace_id = new_trace_id()
        _trace_id_var.set(trace_id)
    return trace_id


def set_trace_id(trace_id: str) -> None:
    _trace_id_var.set(trace_id)
