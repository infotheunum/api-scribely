from __future__ import annotations

from common.settings import CommonSettings
from rewrite_app.rewrite.provider_clients import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_QWEN_BASE_URL,
    DEFAULT_QWEN_MODEL,
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
    # Cheap text models by default (Haiku / 4o-mini / qwen-plus).
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    # DashScope key — also accepted as DASHSCOPE_API_KEY via alias below.
    qwen_api_key: str = ""
    dashscope_api_key: str = ""
    anthropic_model: str = DEFAULT_ANTHROPIC_MODEL
    openai_model: str = DEFAULT_OPENAI_MODEL
    qwen_model: str = DEFAULT_QWEN_MODEL
    qwen_base_url: str = DEFAULT_QWEN_BASE_URL
    # Comma-separated primary slots allowed in article RR (qwen,openai,anthropic).
    # Empty = all keys that are set. Example for Qwen-only: LLM_ENABLED_PROVIDERS=qwen
    # OpenRouter (key_1/2/3) is never in article RR regardless of this setting.
    llm_enabled_providers: str = ""

    def openrouter_keys(self) -> dict[str, str]:
        return {
            "key_1": self.openrouter_key_1,
            "key_2": self.openrouter_key_2,
            "key_3": self.openrouter_key_3,
        }

    def resolved_qwen_api_key(self) -> str:
        return (self.qwen_api_key or self.dashscope_api_key or "").strip()

    def enabled_primary_aliases(self) -> list[str] | None:
        """None = no filter (all configured primaries). Else allow-list order."""
        raw = (self.llm_enabled_providers or "").strip()
        if not raw:
            return None
        aliases = [part.strip().lower() for part in raw.split(",") if part.strip()]
        return aliases or None

    def llm_provider_keys(self) -> dict[str, str]:
        """Rotation slots: paid primaries (+ OpenRouter keys kept for legacy tooling).

        Article RR only uses primaries; OpenRouter is never called for articles.
        ``LLM_ENABLED_PROVIDERS`` can blank out openai/anthropic while keys stay in env.
        """
        keys = {
            **self.openrouter_keys(),
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
            "qwen": self.resolved_qwen_api_key(),
        }
        enabled = self.enabled_primary_aliases()
        if enabled is not None:
            allowed = set(enabled)
            for alias in ("qwen", "openai", "anthropic"):
                if alias not in allowed:
                    keys[alias] = ""
        return keys

    def configured_llm_key_count(self) -> int:
        return sum(1 for value in self.llm_provider_keys().values() if value)
