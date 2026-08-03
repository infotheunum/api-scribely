from __future__ import annotations

from common.settings import CommonSettings


class ApiSettings(CommonSettings):
    service_name: str = "api"
    port: int = 8000

    # INSECURE default — must be overridden via Railway Variables in any
    # real deployment (ТЗ §5: secrets not committed / not hardcoded).
    jwt_secret: str = "dev-insecure-jwt-secret"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12
