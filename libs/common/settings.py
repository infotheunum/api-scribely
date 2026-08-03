from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class CommonSettings(BaseSettings):
    """Config shared by all three services (ТЗ §6.3).

    Service-specific settings (OpenRouter keys, JWT secret, keyword-provider
    keys, ...) live in each service's own settings module and extend this
    one — secrets never live here so they can't leak across service
    boundaries (ТЗ §5, §6.6).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/unum_news"

    rewrite_grpc_address: str = "localhost:50051"

    # Internal service-token auth between api/worker <-> rewrite, over
    # Railway private networking — not mTLS in MVP (ТЗ §5, §6.6, решение 32).
    internal_service_token: str = "dev-insecure-service-token"

    trace_id_header: str = "X-Trace-Id"
