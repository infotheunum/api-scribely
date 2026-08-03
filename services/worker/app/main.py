from __future__ import annotations

from contextlib import asynccontextmanager

import grpc
from common.http_middleware import TraceIdMiddleware
from common.logging import configure_logging
from fastapi import FastAPI, HTTPException, Request, status
from worker_app.grpc_client.client import build_rewrite_channel, check_rewrite_health
from worker_app.scheduler import build_scheduler
from worker_app.settings import WorkerSettings

settings = WorkerSettings()
configure_logging(settings.service_name, settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.rewrite_channel = build_rewrite_channel(settings)
    app.state.scheduler = build_scheduler()
    app.state.scheduler.start()
    yield
    app.state.scheduler.shutdown(wait=False)
    app.state.rewrite_channel.close()


def create_app() -> FastAPI:
    app = FastAPI(title="UNUM Rewriter Tool Worker", lifespan=lifespan)
    app.add_middleware(TraceIdMiddleware)

    @app.get("/health", tags=["health"])
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/health/rewrite", tags=["health"])
    def health_rewrite(request: Request) -> dict:
        try:
            healthy = check_rewrite_health(request.app.state.rewrite_channel)
        except grpc.RpcError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"rewrite service unreachable: {exc.code()}",
            ) from exc
        if not healthy:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="rewrite service not serving",
            )
        return {"status": "ok"}

    return app


app = create_app()
