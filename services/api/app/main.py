from __future__ import annotations

from contextlib import asynccontextmanager

from api_app.grpc_client.client import build_rewrite_channel
from api_app.routers import auth, health, ingestion
from api_app.settings import ApiSettings
from common.http_middleware import TraceIdMiddleware
from common.logging import configure_logging
from fastapi import FastAPI

settings = ApiSettings()
configure_logging(settings.service_name, settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.rewrite_channel = build_rewrite_channel(settings)
    yield
    app.state.rewrite_channel.close()


def create_app() -> FastAPI:
    app = FastAPI(title="UNUM Rewriter Tool API", lifespan=lifespan)
    app.add_middleware(TraceIdMiddleware)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(ingestion.router)
    return app


app = create_app()
