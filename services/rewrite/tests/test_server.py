from __future__ import annotations

import grpc
import pytest
from grpc_health.v1 import health_pb2, health_pb2_grpc
from rewrite_app.server import RPC_SERVICE_NAME, build_server
from rewrite_app.settings import RewriteSettings
from scribely.rewrite.v1 import rewrite_pb2, rewrite_pb2_grpc

TOKEN = "test-token"


@pytest.fixture
def server_address():
    settings = RewriteSettings(grpc_port=0, internal_service_token=TOKEN)
    server = build_server(settings)
    port = server.add_insecure_port("0.0.0.0:0")
    server.start()
    try:
        yield f"localhost:{port}"
    finally:
        server.stop(grace=None)


def _channel(address: str) -> grpc.Channel:
    return grpc.insecure_channel(address)


def _md():
    return (("x-service-token", TOKEN),)


def test_health_check_serving(server_address):
    with _channel(server_address) as channel:
        stub = health_pb2_grpc.HealthStub(channel)
        resp = stub.Check(health_pb2.HealthCheckRequest(service=""), metadata=_md())
        assert resp.status == health_pb2.HealthCheckResponse.SERVING

        resp = stub.Check(health_pb2.HealthCheckRequest(service=RPC_SERVICE_NAME), metadata=_md())
        assert resp.status == health_pb2.HealthCheckResponse.SERVING


def test_missing_service_token_is_rejected(server_address):
    with _channel(server_address) as channel:
        stub = health_pb2_grpc.HealthStub(channel)
        with pytest.raises(grpc.RpcError) as exc_info:
            stub.Check(health_pb2.HealthCheckRequest(service=""))
        assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED


def test_rewrite_cluster_stub_is_unimplemented(server_address):
    with _channel(server_address) as channel:
        stub = rewrite_pb2_grpc.RewriteServiceStub(channel)
        with pytest.raises(grpc.RpcError) as exc_info:
            stub.RewriteCluster(rewrite_pb2.RewriteClusterRequest(), metadata=_md())
        assert exc_info.value.code() == grpc.StatusCode.UNIMPLEMENTED
