"""Machine-readable Export API filter catalog for admin / VPS cron UI."""

from __future__ import annotations

from typing import Any, Literal

from db.enums import DraftStatus

FreshnessPreset = Literal["today", "48h"]

# Query params implemented on GET /drafts and (subset) GET /drafts/today
SUPPORTED_EXPORT_LIST_FILTERS: list[dict[str, Any]] = [
    {
        "name": "consumed",
        "type": "boolean",
        "default": None,
        "enum": [True, False, None],
        "db_field": "draft_export_log.draft_id",
        "description": (
            "false — только ещё не помеченные (живая очередь theunum). "
            "true — только уже mark-consumed. "
            "omit/null — все черновики за период (отладка). "
            "theunum sync всегда шлёт consumed=false; mark-consumed — на "
            "одобрить / отклонить / удалить из очереди, не на sync."
        ),
        "endpoints": ["/drafts", "/drafts/today"],
        "admin_default_key": None,
    },
    {
        "name": "status",
        "type": "string[]",
        "default": [DraftStatus.READY_FOR_REVIEW.value, DraftStatus.NEEDS_FIX.value],
        "enum": [s.value for s in DraftStatus],
        "db_field": "draft.status",
        "description": "Фильтр по статусу черновика. Повтор параметра в query или массив.",
        "endpoints": ["/drafts", "/drafts/today"],
        "admin_default_key": None,
    },
    {
        "name": "since",
        "type": "datetime",
        "default": None,
        "format": "ISO8601",
        "db_field": "draft.updated_at",
        "description": "Любое изменение черновика (не AI-дата). content_generated_at не затрагивает.",
        "endpoints": ["/drafts"],
        "admin_default_key": None,
    },
    {
        "name": "generated_since",
        "type": "datetime",
        "default": None,
        "format": "ISO8601",
        "db_field": "draft.content_generated_at",
        "description": "Нижняя граница даты последнего AI-рерайта/regen.",
        "endpoints": ["/drafts"],
        "admin_default_key": None,
    },
    {
        "name": "freshness",
        "type": "enum",
        "default": None,
        "enum": ["today", "48h"],
        "db_field": "draft.created_at (48h) / draft.content_generated_at (today)",
        "description": (
            "today — AI-рерайт с UTC 00:00 текущих суток (content_generated_at). "
            "48h — черновик создан за последние 48 часов (created_at), "
            "чтобы не тянуть протухшие новости после regen. "
            "max_age_hours/generated_since по-прежнему режут content_generated_at "
            "и комбинируются через AND."
        ),
        "endpoints": ["/drafts"],
        "admin_default_key": "integration.export.default_freshness",
    },
    {
        "name": "max_age_hours",
        "type": "integer",
        "default": None,
        "min": 1,
        "max": 168,
        "db_field": "draft.content_generated_at",
        "description": "Скользящее окно: не старше N часов от now (UTC).",
        "endpoints": ["/drafts"],
        "admin_default_key": "integration.export.default_max_age_hours",
    },
    {
        "name": "limit",
        "type": "integer",
        "default": 50,
        "min": 1,
        "max": 100,
        "db_field": None,
        "description": "Размер страницы списка.",
        "endpoints": ["/drafts", "/drafts/today"],
        "admin_default_key": "integration.export.default_limit",
    },
    {
        "name": "cursor",
        "type": "uuid",
        "default": None,
        "db_field": "draft.id",
        "description": "Курсор пагинации — draft_id из next_cursor предыдущего ответа.",
        "endpoints": ["/drafts", "/drafts/today"],
        "admin_default_key": None,
    },
]

IMPLICIT_EXPORT_RULES: list[dict[str, str]] = [
    {
        "rule": "sort_order",
        "value": "draft.created_at ASC, draft.id ASC",
        "description": "Сортировка фиксирована, параметра order/sort_by нет.",
    },
    {
        "rule": "freshness_source",
        "value": "meta.freshness_source",
        "description": "query | admin_default | none — откуда взяты freshness-дефолты.",
    },
    {
        "rule": "drafts_today_freshness",
        "value": "always today",
        "description": "GET /drafts/today всегда freshness=today; admin defaults не применяются.",
    },
]

# Explicitly not implemented — do not send these query params
UNSUPPORTED_EXPORT_FILTERS: list[dict[str, str]] = [
    {"name": "topic", "reason": "topic только в теле ответа item, фильтра нет"},
    {"name": "category_id / pending_category_slug", "reason": "нет фильтра по категории"},
    {"name": "tag_ids / pending_tags", "reason": "нет фильтра по тегам"},
    {"name": "language", "reason": "EN+RU всегда в одном item"},
    {"name": "body_min_chars / body_max_chars", "reason": "нет фильтра по длине текста"},
    {"name": "similarity_score", "reason": "нет фильтра по similarity"},
    {"name": "sensitive_hold / fact_conflict / sponsor_flag", "reason": "нет фильтра по compliance-флагам"},
    {"name": "needs_attention", "reason": "computed поле, фильтра нет"},
    {"name": "rewrite_llm_model", "reason": "нет фильтра по модели LLM"},
    {"name": "source_name / source_url", "reason": "нет фильтра по RSS-источнику"},
    {"name": "assignee_user_id", "reason": "нет фильтра по rewriter"},
    {"name": "created_since / created_before", "reason": "нет — только cursor по created_at"},
    {"name": "updated_before", "reason": "нет upper bound для updated_at"},
    {"name": "content_generated_before", "reason": "нет upper bound для content_generated_at"},
    {"name": "consumed_since", "reason": "только boolean consumed, не дата consumed_at"},
    {"name": "freshness=24h|7d|week", "reason": "только today и 48h; иначе max_age_hours"},
    {"name": "timezone for today", "reason": "today всегда UTC midnight"},
    {"name": "offset / page / skip", "reason": "только cursor-пагинация"},
    {"name": "order / sort_by / order=desc", "reason": "сортировка фиксирована"},
    {"name": "fields / sparse response", "reason": "всегда полный DraftDetail"},
]


def build_export_schema_payload(db) -> dict[str, Any]:
    """Full filter catalog + current admin defaults (for admin UI / VPS cron builder)."""
    from common.integration_export_settings import load_export_defaults

    return {
        "defaults": load_export_defaults(db),
        "filters": SUPPORTED_EXPORT_LIST_FILTERS,
        "unsupported": UNSUPPORTED_EXPORT_FILTERS,
        "implicit_rules": IMPLICIT_EXPORT_RULES,
        "endpoints": {
            "list": "/integrations/theunum/v1/drafts",
            "today": "/integrations/theunum/v1/drafts/today",
            "detail": "/integrations/theunum/v1/drafts/{id}",
            "mark_consumed": "/integrations/theunum/v1/drafts/mark-consumed",
            "status": "/integrations/theunum/v1/status",
        },
    }
