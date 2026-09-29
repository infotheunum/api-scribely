from __future__ import annotations

from common.settings import CommonSettings


class WorkerSettings(CommonSettings):
    """Scheduler + Ingestion + Dedup + Filter + Compliance (ТЗ §6.3).
    Real scheduling/ingestion logic lands in Phase 1 — Phase 0 only needs
    the service deployed and reachable (health + gRPC client to rewrite)."""

    service_name: str = "worker"
    # No "port" field: same reasoning as ApiSettings — Dockerfile CMD
    # binds uvicorn to shell $PORT directly.

    # Preload SentenceTransformer at boot. Default off: torch+MiniLM is the
    # bulk of Railway RAM cost; load on first clustering tick instead.
    worker_embed_warmup: bool = False
