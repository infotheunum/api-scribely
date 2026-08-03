from __future__ import annotations

from common.settings import CommonSettings


class RewriteSettings(CommonSettings):
    """scribely-rewrite (ТЗ §6.6). OpenRouter/keyword-provider keys are
    introduced in Phase 4 together with the Rotation Manager — not needed
    for the Phase 0 skeleton."""

    # Not named "port": Railway auto-injects a PORT env var on every
    # service (meant for the public HTTP proxy), and pydantic-settings
    # matches env vars to field names case-insensitively — a field named
    # "port" would silently pick up Railway's PORT instead of this
    # default, which is exactly what happened before this was renamed.
    grpc_port: int = 50051
    service_name: str = "rewrite"
