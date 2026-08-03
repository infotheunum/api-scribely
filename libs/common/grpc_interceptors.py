from __future__ import annotations

import collections
from collections.abc import Callable

import grpc

from common.tracing import TRACE_ID_METADATA_KEY, get_trace_id, new_trace_id, set_trace_id

SERVICE_TOKEN_METADATA_KEY = "x-service-token"


class _ClientCallDetails(
    collections.namedtuple(
        "_ClientCallDetails",
        ("method", "timeout", "metadata", "credentials", "wait_for_ready", "compression"),
    ),
    grpc.ClientCallDetails,
):
    pass


def _with_extra_metadata(
    client_call_details: grpc.ClientCallDetails, extra: list[tuple[str, str]]
) -> _ClientCallDetails:
    metadata = list(client_call_details.metadata or [])
    metadata.extend(extra)
    return _ClientCallDetails(
        client_call_details.method,
        client_call_details.timeout,
        metadata,
        client_call_details.credentials,
        client_call_details.wait_for_ready,
        client_call_details.compression,
    )


class ClientAuthTraceInterceptor(
    grpc.UnaryUnaryClientInterceptor, grpc.UnaryStreamClientInterceptor
):
    """Attaches the internal service-token and the current trace_id to
    every outgoing call from api/worker to scribely-rewrite (ТЗ §4.20,
    §6.6). Used for both unary-unary and unary-streaming methods; add
    stream-* variants here if scribely-rewrite ever gains a streaming RPC.
    """

    def __init__(self, service_token: str):
        self._service_token = service_token

    def _extra_metadata(self) -> list[tuple[str, str]]:
        return [
            (SERVICE_TOKEN_METADATA_KEY, self._service_token),
            (TRACE_ID_METADATA_KEY, get_trace_id()),
        ]

    def intercept_unary_unary(
        self,
        continuation: Callable,
        client_call_details: grpc.ClientCallDetails,
        request,
    ):
        details = _with_extra_metadata(client_call_details, self._extra_metadata())
        return continuation(details, request)

    def intercept_unary_stream(
        self,
        continuation: Callable,
        client_call_details: grpc.ClientCallDetails,
        request,
    ):
        details = _with_extra_metadata(client_call_details, self._extra_metadata())
        return continuation(details, request)


class ServerAuthTraceInterceptor(grpc.ServerInterceptor):
    """Server-side counterpart: rejects calls without the expected
    service-token (internal auth between Railway-private services, ТЗ §5,
    §6.6, решение 32 — no mTLS in MVP) and propagates trace_id into the
    handler's context for logging (ТЗ §4.20)."""

    def __init__(self, expected_token: str):
        self._expected_token = expected_token
        self._unauthenticated = grpc.unary_unary_rpc_method_handler(self._deny)

    @staticmethod
    def _deny(request, context: grpc.ServicerContext):
        context.abort(grpc.StatusCode.UNAUTHENTICATED, "missing or invalid service token")

    def intercept_service(self, continuation, handler_call_details: grpc.HandlerCallDetails):
        metadata = dict(handler_call_details.invocation_metadata or [])
        if metadata.get(SERVICE_TOKEN_METADATA_KEY) != self._expected_token:
            return self._unauthenticated
        set_trace_id(metadata.get(TRACE_ID_METADATA_KEY) or new_trace_id())
        return continuation(handler_call_details)
