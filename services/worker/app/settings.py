from __future__ import annotations

from common.settings import CommonSettings


class WorkerSettings(CommonSettings):
    """Scheduler + Ingestion + Dedup + Filter + Compliance (ТЗ §6.3).
    Real scheduling/ingestion logic lands in Phase 1 — Phase 0 only needs
    the service deployed and reachable (health + gRPC client to rewrite)."""

    service_name: str = "worker"
    port: int = 8001
