from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from api_app.grpc_client.client import build_rewrite_channel
from api_app.routers import admin, auth, drafts, health, ingestion, integration_theunum
from api_app.settings import ApiSettings
from api_app.ui.admin_router import router as ui_admin_router
from api_app.ui.router import router as ui_router
from api_app.websocket.router import router as ws_router
from common.http_middleware import TraceIdMiddleware
from common.logging import configure_logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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
    cors_origins = settings.cors_origin_list()
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Theunum-Service-Token"],
            allow_credentials=False,
        )
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(ingestion.router)
    app.include_router(admin.router)
    app.include_router(drafts.router)
    app.include_router(integration_theunum.router)
    app.include_router(ui_router)
    app.include_router(ui_admin_router)
    app.include_router(ws_router)
    app.mount(
        "/ui/static",
        StaticFiles(directory=str(Path(__file__).parent / "ui" / "static")),
        name="ui-static",
    )
    return app


app = create_app()
