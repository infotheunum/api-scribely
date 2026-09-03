from __future__ import annotations

from contextlib import asynccontextmanager

import grpc
from common.http_middleware import TraceIdMiddleware
from common.logging import configure_logging
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from worker_app.db import get_db
from worker_app.dedup.embeddings import embed_text
from worker_app.dispatch.regenerate import run_regenerate_batch
from worker_app.grpc_client.client import build_rewrite_channel, check_rewrite_health
from worker_app.scheduler import build_scheduler
from worker_app.settings import WorkerSettings

settings = WorkerSettings()
configure_logging(settings.service_name, settings.log_level)


class RegenerateBatchIn(BaseModel):
    all_queue: bool = Field(
        default=True,
        description="True = all ready_for_review/needs_fix; False = only short bodies",
    )
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    clear_export: bool = Field(
        default=True,
        description="Clear draft_export_log so theunum Export API returns regen drafts",
    )


def _require_internal_token(x_internal_service_token: str = Header(...)) -> None:
    if x_internal_service_token != settings.internal_service_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid internal service token")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.rewrite_channel = build_rewrite_channel(settings)
    embed_text("warmup")
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

    @app.post("/internal/regenerate-drafts", tags=["internal"])
    def regenerate_drafts_batch(
        body: RegenerateBatchIn,
        db=Depends(get_db),
        _: None = Depends(_require_internal_token),
    ) -> dict:
        return run_regenerate_batch(
            db,
            settings=settings,
            all_queue=body.all_queue,
            limit=body.limit,
            offset=body.offset,
            clear_export=body.clear_export,
        )

    return app


app = create_app()
