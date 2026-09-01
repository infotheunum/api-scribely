from __future__ import annotations

from common.settings import CommonSettings
from pydantic import field_validator


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

    # Machine-to-machine auth for api.theunum.io cron (integrations API).
    theunum_integration_token: str = ""

    # Comma-separated browser origins; empty = CORS middleware disabled.
    cors_allowed_origins: str = ""

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _normalize_cors_origins(cls, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return ",".join(str(item).strip() for item in value if str(item).strip())
        return str(value)

    def cors_origin_list(self) -> list[str]:
        if not self.cors_allowed_origins.strip():
            return []
        return [part.strip() for part in self.cors_allowed_origins.split(",") if part.strip()]
