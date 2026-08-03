from __future__ import annotations

from common.settings import CommonSettings


class ApiSettings(CommonSettings):
    service_name: str = "api"
    # No "port" field: the Dockerfile CMD binds uvicorn to shell $PORT
    # directly (Railway-injected) — a Python field here would be unused
    # dead config at best, and a name collision footgun at worst (see
    # RewriteSettings.grpc_port for what that footgun looks like live).

    # INSECURE default — must be overridden via Railway Variables in any
    # real deployment (ТЗ §5: secrets not committed / not hardcoded).
    jwt_secret: str = "dev-insecure-jwt-secret"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12
