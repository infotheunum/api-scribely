from __future__ import annotations

import logging
import signal
from concurrent import futures

import grpc
from common.grpc_interceptors import ServerAuthTraceInterceptor
from common.logging import configure_logging
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from rewrite_app.servicer import RewriteServicer
from rewrite_app.settings import RewriteSettings
from scribely.rewrite.v1 import rewrite_pb2_grpc

logger = logging.getLogger(__name__)

RPC_SERVICE_NAME = "scribely.rewrite.v1.RewriteService"


def build_server(settings: RewriteSettings) -> grpc.Server:
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        interceptors=[ServerAuthTraceInterceptor(settings.internal_service_token)],
    )

    rewrite_pb2_grpc.add_RewriteServiceServicer_to_server(RewriteServicer(), server)

    health_servicer = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    health_servicer.set(RPC_SERVICE_NAME, health_pb2.HealthCheckResponse.SERVING)

    # Railway's private network (*.railway.internal, used by api/worker to
    # reach this service) is IPv6-only — binding "0.0.0.0" (IPv4-only)
    # leaves it unreachable there even though the container itself is
    # healthy. "[::]" is the IPv6 wildcard; on Linux it dual-stacks and
    # also accepts IPv4 connections, so this covers both cases.
    server.add_insecure_port(f"[::]:{settings.grpc_port}")
    return server


def serve() -> None:
    settings = RewriteSettings()
    configure_logging(settings.service_name, settings.log_level)
    server = build_server(settings)
    server.start()
    logger.info("scribely-rewrite listening on :%s", settings.grpc_port)

    def _handle_stop(signum, frame):
        logger.info("received signal %s, shutting down", signum)
        server.stop(grace=5)

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    server.wait_for_termination()


if __name__ == "__main__":
    serve()
