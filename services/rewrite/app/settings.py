from __future__ import annotations

from common.settings import CommonSettings
from rewrite_app.rewrite.provider_clients import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_OPENAI_MODEL,
)


class RewriteSettings(CommonSettings):
    """scribely-rewrite (ТЗ §6.6)."""

    # Not named "port": Railway auto-injects a PORT env var on every
    # service (meant for the public HTTP proxy), and pydantic-settings
    # matches env vars to field names case-insensitively — a field named
    # "port" would silently pick up Railway's PORT instead of this
    # default, which is exactly what happened before this was renamed.
    grpc_port: int = 50051
    service_name: str = "rewrite"

    # OpenRouter — free-tier only, 3 keys for the Rotation Manager (ТЗ
    # §4.5). Empty string default (not required) so the Phase 0/1/2/3
    # skeleton keeps working without them in environments that don't set
    # these; RewriteCluster fails loudly at call time if none are set.
    openrouter_key_1: str = ""
    openrouter_key_2: str = ""
    openrouter_key_3: str = ""

    # Fallback providers after OpenRouter keys are exhausted / missing.
    # Cheap text models by default (Haiku / 4o-mini) — override via env.
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    anthropic_model: str = DEFAULT_ANTHROPIC_MODEL
    openai_model: str = DEFAULT_OPENAI_MODEL

    def openrouter_keys(self) -> dict[str, str]:
        return {
            "key_1": self.openrouter_key_1,
            "key_2": self.openrouter_key_2,
            "key_3": self.openrouter_key_3,
        }

    def llm_provider_keys(self) -> dict[str, str]:
        """All rotation slots: OpenRouter keys + Anthropic + OpenAI."""
        return {
            **self.openrouter_keys(),
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
        }

    def configured_llm_key_count(self) -> int:
        return sum(1 for value in self.llm_provider_keys().values() if value)
