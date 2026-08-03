from __future__ import annotations

import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc
from scribely.rewrite.v1 import rewrite_pb2_grpc

from common.grpc_interceptors import ClientAuthTraceInterceptor
from common.settings import CommonSettings


def build_rewrite_channel(settings: CommonSettings) -> grpc.Channel:
    """Channel to scribely-rewrite over Railway private networking, with
    service-token + trace_id attached to every call (ТЗ §6.6). Shared by
    api and worker — both are plain gRPC clients to rewrite, nothing
    service-specific about building the channel itself."""
    channel = grpc.insecure_channel(settings.rewrite_grpc_address)
    return grpc.intercept_channel(
        channel, ClientAuthTraceInterceptor(settings.internal_service_token)
    )


def rewrite_stub(channel: grpc.Channel) -> rewrite_pb2_grpc.RewriteServiceStub:
    return rewrite_pb2_grpc.RewriteServiceStub(channel)


def check_rewrite_health(channel: grpc.Channel, timeout: float = 5.0) -> bool:
    stub = health_pb2_grpc.HealthStub(channel)
    response = stub.Check(health_pb2.HealthCheckRequest(service=""), timeout=timeout)
    return response.status == health_pb2.HealthCheckResponse.SERVING
