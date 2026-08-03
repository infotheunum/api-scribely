from __future__ import annotations

from common.settings import CommonSettings


class RewriteSettings(CommonSettings):
    """scribely-rewrite (ТЗ §6.6). OpenRouter/keyword-provider keys are
    introduced in Phase 4 together with the Rotation Manager — not needed
    for the Phase 0 skeleton."""

    port: int = 50051
    service_name: str = "rewrite"
