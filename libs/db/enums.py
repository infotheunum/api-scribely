from __future__ import annotations

import enum


class SourceType(enum.StrEnum):
    RSS = "rss"
    API = "api"


class SourceTier(int, enum.Enum):
    """Уровни 1-6 Приложения 1 редполитики."""

    TIER_1 = 1
    TIER_2 = 2
    TIER_3 = 3
    TIER_4 = 4
    TIER_5 = 5
    TIER_6 = 6


class TopicStatus(enum.StrEnum):
    """Флаг «в теме/не в теме» кластера (ТЗ §4.3)."""

    PENDING = "pending"
    IN_TOPIC = "in_topic"
    OUT_OF_TOPIC = "out_of_topic"


class DraftStatus(enum.StrEnum):
    """Жизненный цикл черновика (ТЗ §6.5). New/Clustered предшествуют
    созданию строки Draft — она появляется уже в состоянии DRAFTING."""

    DRAFTING = "drafting"
    READY_FOR_REVIEW = "ready_for_review"
    NEEDS_FIX = "needs_fix"
    PUBLISHED = "published"
    REJECTED = "rejected"
    SNOOZED = "snoozed"
    ARCHIVED = "archived"
    UPDATED = "updated"


class DraftRevisionKind(enum.StrEnum):
    AI_GENERATED = "ai_generated"
    HUMAN_FINAL = "human_final"
    REGEN = "regen"


class EditSignalCategory(enum.StrEnum):
    FACT = "fact"
    STYLE = "style"
    TITLE = "title"
    ATTRIBUTION = "attribution"
    LENGTH = "length"
    TONE = "tone"
    TRANSLATION = "translation"
    SEO = "seo"
    TAGS = "tags"
    IMAGE = "image"


class PromptVersionStatus(enum.StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class DraftLockMode(enum.StrEnum):
    VIEWING = "viewing"
    EDITING = "editing"


class TagCategoryKind(enum.StrEnum):
    TAG = "tag"
    CATEGORY = "category"


class UserRole(enum.StrEnum):
    REWRITER = "rewriter"
    ADMIN = "admin"
    EDITOR_IN_CHIEF = "editor_in_chief"  # резерв на будущее, не в MVP UI (ТЗ §3)


class RejectReason(enum.StrEnum):
    """Обязательный enum причины Reject/NeedsFix (ТЗ §4.7, §4.13) —
    не свободный текст без категории."""

    FACTUAL_ERROR = "factual_error"
    POLICY_VIOLATION = "policy_violation"
    LOW_QUALITY = "low_quality"
    DUPLICATE = "duplicate"
    OFF_TOPIC = "off_topic"
    NEEDS_MORE_SOURCES = "needs_more_sources"
    TRANSLATION_ISSUE = "translation_issue"
    OTHER = "other"
