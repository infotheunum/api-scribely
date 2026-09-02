from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base
from db.enums import (
    DraftLockMode,
    DraftRevisionKind,
    DraftStatus,
    EditSignalCategory,
    PromptVersionStatus,
    SourceTier,
    SourceType,
    TagCategoryKind,
    TopicStatus,
    UserRole,
)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    """ТЗ §3, §6.4. Тестовый Rewriter — настоящий сотрудник редакции UNUM,
    не заглушка."""

    __tablename__ = "user"

    id: Mapped[uuid.UUID] = _uuid_pk()
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(String(32), nullable=False, default=UserRole.REWRITER)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created_at()


class Source(Base):
    """ТЗ §4.1, §6.4. Конфигурируемый реестр — добавление источника не
    требует изменения кода."""

    __tablename__ = "source"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    type: Mapped[SourceType] = mapped_column(String(16), nullable=False)
    tier: Mapped[SourceTier] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    # Per-source RssConnector config (headers, auth, feed-specific quirks) —
    # 1 universal connector + config, not 1 adapter per source (реестр §0).
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Circuit breaker bookkeeping (ТЗ §4.20).
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = _created_at()

    raw_items: Mapped[list[RawItem]] = relationship(back_populates="source")


class RawItem(Base):
    """ТЗ §4.1, §6.4. external_id — guid/link для идемпотентности опроса,
    в т.ч. ручного inject (ТЗ §4.20)."""

    __tablename__ = "raw_item"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_raw_item_source_external_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    is_full_text: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = _created_at()
    is_manual_inject: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("news_cluster.id"))
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Multilingual sentence embedding (title + excerpt) for cross-language
    # clustering (ТЗ §4.2, План §4) — computed locally (sentence-
    # transformers), not via OpenRouter. Plain float array, not pgvector:
    # similarity is compared in Python against a small recent-cluster
    # window, well within scale for ~100-300 items/day (ТЗ §5).
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float))

    source: Mapped[Source] = relationship(back_populates="raw_items")
    cluster: Mapped[NewsCluster | None] = relationship(back_populates="raw_items")


class NewsCluster(Base):
    """ТЗ §4.2, §6.4. Кросс-языковая группировка Raw Item по событию."""

    __tablename__ = "news_cluster"

    id: Mapped[uuid.UUID] = _uuid_pk()
    topic: Mapped[str | None] = mapped_column(String(255))
    topic_status: Mapped[TopicStatus] = mapped_column(
        String(16), nullable=False, default=TopicStatus.PENDING
    )
    priority_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    # Centroid embedding — the arriving item's own embedding when the
    # cluster is created; not recomputed as a running average in MVP
    # (would need care around drift as unrelated-but-similar items pile
    # on; the first item's embedding is a fine anchor at this volume).
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float))

    raw_items: Mapped[list[RawItem]] = relationship(back_populates="cluster")
    context: Mapped[ClusterContext | None] = relationship(back_populates="cluster", uselist=False)
    drafts: Mapped[list[Draft]] = relationship(back_populates="cluster")


class ClusterContext(Base):
    """ТЗ §4.12, §6.4. 1:1 с NewsCluster. Факты/флаги, извлечённые из уже
    сохранённых RawItem.body (Enrichment не перезабирает текст заново)."""

    __tablename__ = "cluster_context"

    cluster_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("news_cluster.id"), primary_key=True)
    # [{"kind": "who|what|when|number|quote", "text": ..., "supporting_raw_item_ids": [...]}]
    facts: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    press_release: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    regulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    market_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fact_conflict: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fact_conflict_note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    cluster: Mapped[NewsCluster] = relationship(back_populates="context")


class PromptVersion(Base):
    """ТЗ §4.13, §6.4."""

    __tablename__ = "prompt_version"

    id: Mapped[uuid.UUID] = _uuid_pk()
    template: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[PromptVersionStatus] = mapped_column(
        String(16), nullable=False, default=PromptVersionStatus.DRAFT
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class Draft(Base):
    """ТЗ §4.4-§4.20, §6.4. Центральная сущность — AI-рерайт кластера
    (EN+RU) с SEO-пакетом, брифом обложки, тегами-кандидатами и
    compliance-флагами."""

    __tablename__ = "draft"

    id: Mapped[uuid.UUID] = _uuid_pk()
    cluster_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("news_cluster.id"), nullable=False)

    title_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    title_ru: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_ru: Mapped[str] = mapped_column(Text, nullable=False, default="")
    title_en_variants: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    title_ru_variants: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    attribution_urls: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)

    sponsor_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    press_release_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    disclaimer_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    similarity_score: Mapped[float | None] = mapped_column(Float)
    fact_conflict: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Compliance gate (ТЗ §4.6, §4.20, Фаза 5). sensitive_hold is a
    # stronger, separately-visible hold than the regular flags above
    # (sanctions/crime/death/hack topics, §11.4 редполитики) — a draft
    # can be sensitive_hold=True while still status=NEEDS_FIX, or even
    # while status=READY_FOR_REVIEW if the rest of the gate passed but
    # extra editorial caution is still warranted. compliance_notes is the
    # human-readable trail of which rule(s) fired, for the eventual
    # review UI (Фаза 6) and for debugging the rules themselves.
    sensitive_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    compliance_notes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)

    # LLM key/model actually used, for rotation audit (ТЗ §4.5, §4.10).
    rewrite_llm_key_alias: Mapped[str | None] = mapped_column(String(32))
    rewrite_llm_model: Mapped[str | None] = mapped_column(String(255))
    translate_llm_key_alias: Mapped[str | None] = mapped_column(String(32))
    translate_llm_model: Mapped[str | None] = mapped_column(String(255))

    # Token usage for the last enrich+rewrite cycle that produced this draft.
    llm_prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[DraftStatus] = mapped_column(
        String(20), nullable=False, default=DraftStatus.DRAFTING
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # ТЗ §4.15
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("prompt_version.id"))
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id"))

    # SEO-пакет EN+RU (ТЗ §4.16).
    seo_title_en: Mapped[str | None] = mapped_column(String(512))
    seo_description_en: Mapped[str | None] = mapped_column(Text)
    slug_en: Mapped[str | None] = mapped_column(String(512))
    og_title_en: Mapped[str | None] = mapped_column(String(512))
    og_description_en: Mapped[str | None] = mapped_column(Text)
    focus_keyphrase_en: Mapped[str | None] = mapped_column(String(255))
    keywords_en: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    seo_title_ru: Mapped[str | None] = mapped_column(String(512))
    seo_description_ru: Mapped[str | None] = mapped_column(Text)
    slug_ru: Mapped[str | None] = mapped_column(String(512))
    og_title_ru: Mapped[str | None] = mapped_column(String(512))
    og_description_ru: Mapped[str | None] = mapped_column(Text)
    focus_keyphrase_ru: Mapped[str | None] = mapped_column(String(255))
    keywords_ru: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)

    # Image brief (ТЗ §4.17) — text only, no file in MVP.
    image_brief: Mapped[str | None] = mapped_column(Text)
    image_mood: Mapped[str | None] = mapped_column(String(255))
    image_subjects: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    image_style: Mapped[str | None] = mapped_column(String(255))
    image_do_not: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    image_alt: Mapped[str | None] = mapped_column(String(512))
    image_caption: Mapped[str | None] = mapped_column(Text)
    image_source_suggestion: Mapped[str | None] = mapped_column(String(512))
    image_license_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Snooze handoff (ТЗ §6.3, Фаза 6) — short note left for whoever
    # picks the draft back up; nullable, no backfill concern for prod.
    handoff_note: Mapped[str | None] = mapped_column(Text)

    # Tags/category (ТЗ §4.19) — real theunum.io ids once resolved on
    # Approve, pending_tags[]/pending_category_slug hold LLM candidates
    # until then (SuggestTags never returns a real suggested_category_id
    # today — only a slug guess, see rewrite_app/rewrite/schemas.py).
    category_id: Mapped[str | None] = mapped_column(String(64))
    tag_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    pending_tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    pending_category_slug: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    # ORM default + DB server_default: INSERT may flush before apply_rewrite_content
    # sets the real AI timestamp; without both, NOT NULL fails (prod 2026-09-02).
    content_generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    cluster: Mapped[NewsCluster] = relationship(back_populates="drafts")
    revisions: Mapped[list[DraftRevision]] = relationship(back_populates="draft")
    export_log: Mapped[DraftExportLog | None] = relationship(
        back_populates="draft", uselist=False
    )


class DraftRevision(Base):
    """ТЗ §4.13, §6.4. Снимки ai_generated/human_final/regen для diff и
    обучения промпта — не полная история каждого PATCH."""

    __tablename__ = "draft_revision"

    id: Mapped[uuid.UUID] = _uuid_pk()
    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("draft.id"), nullable=False)
    kind: Mapped[DraftRevisionKind] = mapped_column(String(16), nullable=False)
    title_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    title_ru: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_ru: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id"))
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("prompt_version.id"))
    created_at: Mapped[datetime] = _created_at()

    draft: Mapped[Draft] = relationship(back_populates="revisions")


class DraftExportLog(Base):
    """theunum.io integration — VPS cron marked this draft consumed."""

    __tablename__ = "draft_export_log"

    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("draft.id", ondelete="CASCADE"), primary_key=True)
    consumed_at: Mapped[datetime] = _created_at()
    theunum_reference_id: Mapped[str | None] = mapped_column(String(128))
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)

    draft: Mapped[Draft] = relationship(back_populates="export_log")


class EditSignal(Base):
    """ТЗ §4.13, §6.4. Опционально считается из diff между ревизиями."""

    __tablename__ = "edit_signal"

    id: Mapped[uuid.UUID] = _uuid_pk()
    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("draft.id"), nullable=False)
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id"))
    category: Mapped[EditSignalCategory] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class DraftLock(Base):
    """ТЗ §4.15, §6.4. Soft-lock на editing + presence на viewing. Одна
    строка на (draft_id, user_id); переключение режима обновляет строку.
    Partial unique index не даёт двум editing-локам сосуществовать на
    одном черновике (defense-in-depth поверх WebSocket-логики в api)."""

    __tablename__ = "draft_lock"
    __table_args__ = (
        Index(
            "uq_draft_lock_one_editor_per_draft",
            "draft_id",
            unique=True,
            postgresql_where=text(f"mode = '{DraftLockMode.EDITING.value}'"),
        ),
    )

    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("draft.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"), primary_key=True)
    mode: Mapped[DraftLockMode] = mapped_column(String(16), nullable=False)
    locked_at: Mapped[datetime] = _created_at()
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RewriterStyleCache(Base):
    """ТЗ §4.14, §6.4. Read-through кэш — НЕ мастер. Источник истины —
    theunum.io RewriterStyleProfile (vector store)."""

    __tablename__ = "rewriter_style_cache"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"), primary_key=True)
    summary: Mapped[str | None] = mapped_column(Text)
    preferences_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    embedding_version: Mapped[str | None] = mapped_column(String(64))
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TagCategoryCache(Base):
    """ТЗ §4.19, §6.4. Локальная read-only реплика справочника
    Tag/Category с theunum.io (мастер), для автокомплита в UI."""

    __tablename__ = "tag_category_cache"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # theunum.io id
    kind: Mapped[TagCategoryKind] = mapped_column(String(16), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(255))
    name_ru: Mapped[str | None] = mapped_column(String(255))
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class KeywordResearchCache(Base):
    """ТЗ §4.18, §6.4. Кэш по нормализованной фразе+locale+provider."""

    __tablename__ = "keyword_research_cache"

    normalized_phrase: Mapped[str] = mapped_column(String(512), primary_key=True)
    locale: Mapped[str] = mapped_column(String(8), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    volume: Mapped[int | None] = mapped_column(Integer)
    related: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    fetched_at: Mapped[datetime] = _created_at()


class PublishRecord(Base):
    """ТЗ §4.8, §6.4. external_id/url — поля на будущее, пустые в MVP
    (Publish Adapter no-op); category_id/tag_ids[] — уже реальные (ТЗ §4.19)."""

    __tablename__ = "publish_record"

    id: Mapped[uuid.UUID] = _uuid_pk()
    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("draft.id"), nullable=False)
    published_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id"))
    published_at: Mapped[datetime] = _created_at()
    category_id: Mapped[str | None] = mapped_column(String(64))
    tag_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    external_id: Mapped[str | None] = mapped_column(String(255))
    external_url: Mapped[str | None] = mapped_column(String(2048))
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)


class LLMRotationState(Base):
    """ТЗ §4.5, §6.4. Персистентное состояние ротации по ключу — какая
    модель из списка free-моделей сейчас активна для этого ключа."""

    __tablename__ = "llm_rotation_state"

    key_alias: Mapped[str] = mapped_column(String(32), primary_key=True)  # key_1|key_2|key_3
    current_model_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_switched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LLMRotationUsage(Base):
    """Счётчики использования/ошибок по паре (ключ, модель) — ТЗ §4.5."""

    __tablename__ = "llm_rotation_usage"

    key_alias: Mapped[str] = mapped_column(String(32), primary_key=True)
    model: Mapped[str] = mapped_column(String(255), primary_key=True)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AuditLog(Base):
    """ТЗ §4.10, §6.4. Любое действие с материалом восстановимо из журнала."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = _uuid_pk()
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id"))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Free-form details incl. reject/needs-fix reason enum value and
    # image-license-confirmation flag when relevant to the action.
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    trace_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created_at()


class Topic(Base):
    """ТЗ §4.3, §4.21. Тема редполитики + ключевые слова EN+RU для
    классификации кластеров — заменяет захардкоженный в коде список
    (Фаза 3), редактируется через Admin Settings без редеплоя."""

    __tablename__ = "topic"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class LlmRotationModel(Base):
    """ТЗ §4.5, §4.21. Упорядоченный список free-моделей OpenRouter для
    ротации — заменяет захардкоженный список (Фаза 4). Не более 3
    активных одновременно (жёсткий лимит OpenRouter на длину `models`,
    §4.5 п.6) — валидируется на уровне Admin API, не здесь."""

    __tablename__ = "llm_rotation_model"

    id: Mapped[uuid.UUID] = _uuid_pk()
    model_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created_at()


class AppSetting(Base):
    """ТЗ §4.21. Общий key/value механизм для тонких/грубых настроек
    пайплайна (лимиты очереди, пороги дедупликации, размер пачки
    диспетчера, kill-switches этапов и т.д.) — новый параметр не требует
    миграции схемы, только новую строку. value хранит JSON-скаляр или
    список напрямую (не обёрнут в объект)."""

    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[object] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id"))
