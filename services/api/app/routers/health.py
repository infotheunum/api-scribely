from __future__ import annotations

import grpc
from api_app.grpc_client.client import check_rewrite_health
from fastapi import APIRouter, HTTPException, Request, status

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/health/rewrite")
def health_rewrite(request: Request) -> dict:
    """Confirms api can actually reach scribely-rewrite over the private
    network (Phase 0 demo criterion, ТЗ §6.6), not just that it's
    configured to."""
    try:
        healthy = check_rewrite_health(request.app.state.rewrite_channel)
    except grpc.RpcError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"rewrite service unreachable: {exc.code()}",
        ) from exc
    if not healthy:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="rewrite service not serving"
        )
    return {"status": "ok"}
