from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from api_app.auth.dependencies import require_role
from api_app.db import get_db
from common.tracing import get_trace_id
from db.enums import DraftStatus, PromptVersionStatus, SourceTier, SourceType, TagCategoryKind
from db.models import (
    AppSetting,
    AuditLog,
    ClusterQuarantine,
    Draft,
    LlmRotationModel,
    PromptVersion,
    Source,
    TagCategoryCache,
    Topic,
    User,
)
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_role("admin"))])

MAX_ACTIVE_LLM_MODELS = 3  # ТЗ §4.5 п.6 — жёсткий лимит самого OpenRouter API
_MAX_ACTIVE_MODELS_ERROR = (
    f"at most {MAX_ACTIVE_LLM_MODELS} active models allowed "
    "(OpenRouter `models` array limit, ТЗ §4.5 п.6)"
)


def _audit(
    db: Session, user: User, *, action: str, entity_type: str, entity_id: str, details: dict
) -> None:
    db.add(
        AuditLog(
            actor_id=user.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            trace_id=get_trace_id(),
        )
    )


class QuarantineOut(BaseModel):
    cluster_id: str
    reason: str
    evidence: str
    created_at: str

    @classmethod
    def from_model(cls, row: ClusterQuarantine) -> QuarantineOut:
        return cls(
            cluster_id=str(row.cluster_id),
            reason=str(row.reason),
            evidence=row.evidence,
            created_at=row.created_at.isoformat(),
        )


@router.get("/quarantines", response_model=list[QuarantineOut])
def list_quarantines(db: Session = Depends(get_db)) -> list[QuarantineOut]:
    rows = db.scalars(
        select(ClusterQuarantine)
        .where(ClusterQuarantine.released_at.is_(None))
        .order_by(ClusterQuarantine.created_at.desc())
    )
    return [QuarantineOut.from_model(row) for row in rows]


@router.post("/quarantines/{cluster_id}/release", response_model=QuarantineOut)
def release_quarantine(
    cluster_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
) -> QuarantineOut:
    row = db.scalar(
        select(ClusterQuarantine).where(
            ClusterQuarantine.cluster_id == cluster_id,
            ClusterQuarantine.released_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "active quarantine not found")
    from datetime import UTC, datetime

    row.released_at = datetime.now(UTC)
    row.released_by = user.id
    draft = db.scalar(select(Draft).where(Draft.cluster_id == cluster_id))
    if draft is not None and draft.status == DraftStatus.REJECTED:
        draft.status = DraftStatus.NEEDS_FIX
    _audit(
        db,
        user,
        action="admin_release",
        entity_type="ClusterQuarantine",
        entity_id=str(row.id),
        details={"cluster_id": str(cluster_id), "reason": str(row.reason)},
    )
    return QuarantineOut.from_model(row)


# ---------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------


class SourceIn(BaseModel):
    name: str
    url: str
    type: SourceType = SourceType.RSS
    tier: SourceTier
    language: str = "en"
    is_active: bool = True
    poll_interval_seconds: int = 900


class SourcePatch(BaseModel):
    name: str | None = None
    url: str | None = None
    tier: SourceTier | None = None
    language: str | None = None
    is_active: bool | None = None
    poll_interval_seconds: int | None = None


class SourceOut(BaseModel):
    id: str
    name: str
    url: str
    type: str
    tier: int
    language: str
    is_active: bool
    poll_interval_seconds: int

    @classmethod
    def from_model(cls, source: Source) -> SourceOut:
        return cls(
            id=str(source.id),
            name=source.name,
            url=source.url,
            type=source.type,
            tier=int(source.tier),
            language=source.language,
            is_active=source.is_active,
            poll_interval_seconds=source.poll_interval_seconds,
        )


@router.get("/sources", response_model=list[SourceOut])
def list_sources(db: Session = Depends(get_db)) -> list[SourceOut]:
    rows = db.scalars(
        select(Source)
        .where(Source.deleted_at.is_(None))
        .order_by(Source.name.asc())
    )
    return [SourceOut.from_model(s) for s in rows]


@router.post("/sources", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
def create_source(
    body: SourceIn, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))
) -> SourceOut:
    """Adding a source is configuration, not code (ТЗ §5 НФТ) — it's
    picked up by the very next poll tick that finds it due, no redeploy."""
    source = Source(**body.model_dump())
    db.add(source)
    db.flush()
    _audit(
        db,
        user,
        action="admin_create",
        entity_type="Source",
        entity_id=str(source.id),
        details=body.model_dump(mode="json"),
    )
    return SourceOut.from_model(source)


@router.patch("/sources/{source_id}", response_model=SourceOut)
def update_source(
    source_id: uuid.UUID,
    body: SourcePatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
) -> SourceOut:
    source = db.get(Source, source_id)
    if source is None or source.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source not found")
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(source, field, value)
    _audit(
        db,
        user,
        action="admin_update",
        entity_type="Source",
        entity_id=str(source.id),
        details=changes,
    )
    return SourceOut.from_model(source)


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
) -> None:
    """Soft-delete: hide from Admin registry, stop polling, keep RawItem history."""
    source = db.get(Source, source_id)
    if source is None or source.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source not found")
    source.deleted_at = datetime.now(UTC)
    source.is_active = False
    _audit(
        db,
        user,
        action="admin_delete",
        entity_type="Source",
        entity_id=str(source.id),
        details={"name": source.name, "url": source.url},
    )


# ---------------------------------------------------------------------
# Topic
# ---------------------------------------------------------------------


class TopicIn(BaseModel):
    name: str
    keywords: list[str] = Field(default_factory=list)
    is_active: bool = True


class TopicPatch(BaseModel):
    keywords: list[str] | None = None
    is_active: bool | None = None


class TopicOut(BaseModel):
    id: str
    name: str
    keywords: list[str]
    is_active: bool

    @classmethod
    def from_model(cls, topic: Topic) -> TopicOut:
        return cls(
            id=str(topic.id), name=topic.name, keywords=topic.keywords, is_active=topic.is_active
        )


@router.get("/topics", response_model=list[TopicOut])
def list_topics(db: Session = Depends(get_db)) -> list[TopicOut]:
    return [TopicOut.from_model(t) for t in db.scalars(select(Topic))]


@router.post("/topics", response_model=TopicOut, status_code=status.HTTP_201_CREATED)
def create_topic(
    body: TopicIn, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))
) -> TopicOut:
    if db.scalar(select(Topic).where(Topic.name == body.name)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "a topic with this name already exists")
    topic = Topic(**body.model_dump())
    db.add(topic)
    db.flush()
    _audit(
        db,
        user,
        action="admin_create",
        entity_type="Topic",
        entity_id=str(topic.id),
        details=body.model_dump(),
    )
    return TopicOut.from_model(topic)


@router.patch("/topics/{topic_id}", response_model=TopicOut)
def update_topic(
    topic_id: uuid.UUID,
    body: TopicPatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
) -> TopicOut:
    """Deactivating every topic (is_active=False on all rows) is a valid,
    deliberate state — it doesn't get silently re-seeded (ТЗ §4.21, see
    worker_app/filter/topics.py:active_topics)."""
    topic = db.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "topic not found")
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(topic, field, value)
    _audit(
        db,
        user,
        action="admin_update",
        entity_type="Topic",
        entity_id=str(topic.id),
        details=changes,
    )
    return TopicOut.from_model(topic)


# ---------------------------------------------------------------------
# LlmRotationModel
# ---------------------------------------------------------------------


class LlmModelIn(BaseModel):
    model_id: str
    position: int = 0
    is_active: bool = True


class LlmModelPatch(BaseModel):
    position: int | None = None
    is_active: bool | None = None


class LlmModelOut(BaseModel):
    id: str
    model_id: str
    position: int
    is_active: bool

    @classmethod
    def from_model(cls, model: LlmRotationModel) -> LlmModelOut:
        return cls(
            id=str(model.id),
            model_id=model.model_id,
            position=model.position,
            is_active=model.is_active,
        )


def _count_active_models(db: Session, *, excluding: uuid.UUID | None = None) -> int:
    rows = db.scalars(select(LlmRotationModel).where(LlmRotationModel.is_active.is_(True))).all()
    return sum(1 for r in rows if r.id != excluding)


@router.get("/llm-models", response_model=list[LlmModelOut])
def list_llm_models(db: Session = Depends(get_db)) -> list[LlmModelOut]:
    rows = db.scalars(select(LlmRotationModel).order_by(LlmRotationModel.position)).all()
    return [LlmModelOut.from_model(m) for m in rows]


@router.post("/llm-models", response_model=LlmModelOut, status_code=status.HTTP_201_CREATED)
def create_llm_model(
    body: LlmModelIn, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))
) -> LlmModelOut:
    if body.is_active and _count_active_models(db) >= MAX_ACTIVE_LLM_MODELS:
        raise HTTPException(status.HTTP_409_CONFLICT, _MAX_ACTIVE_MODELS_ERROR)
    if (
        db.scalar(select(LlmRotationModel).where(LlmRotationModel.model_id == body.model_id))
        is not None
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "this model_id is already registered")
    model = LlmRotationModel(**body.model_dump())
    db.add(model)
    db.flush()
    _audit(
        db,
        user,
        action="admin_create",
        entity_type="LlmRotationModel",
        entity_id=str(model.id),
        details=body.model_dump(),
    )
    return LlmModelOut.from_model(model)


@router.patch("/llm-models/{model_id}", response_model=LlmModelOut)
def update_llm_model(
    model_id: uuid.UUID,
    body: LlmModelPatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
) -> LlmModelOut:
    model = db.get(LlmRotationModel, model_id)
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "model not found")
    changes = body.model_dump(exclude_unset=True)
    turning_on = changes.get("is_active") is True and not model.is_active
    if turning_on and _count_active_models(db, excluding=model.id) >= MAX_ACTIVE_LLM_MODELS:
        raise HTTPException(status.HTTP_409_CONFLICT, _MAX_ACTIVE_MODELS_ERROR)
    for field, value in changes.items():
        setattr(model, field, value)
    _audit(
        db,
        user,
        action="admin_update",
        entity_type="LlmRotationModel",
        entity_id=str(model.id),
        details=changes,
    )
    return LlmModelOut.from_model(model)


# ---------------------------------------------------------------------
# AppSetting
# ---------------------------------------------------------------------


class AppSettingIn(BaseModel):
    value: Any
    description: str | None = None


class AppSettingOut(BaseModel):
    key: str
    value: Any
    description: str | None

    @classmethod
    def from_model(cls, setting: AppSetting) -> AppSettingOut:
        return cls(key=setting.key, value=setting.value, description=setting.description)


@router.get("/settings", response_model=list[AppSettingOut])
def list_settings(db: Session = Depends(get_db)) -> list[AppSettingOut]:
    return [AppSettingOut.from_model(s) for s in db.scalars(select(AppSetting))]


@router.put("/settings/{key}", response_model=AppSettingOut)
def upsert_setting(
    key: str,
    body: AppSettingIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
) -> AppSettingOut:
    """Takes effect on the very next scheduler tick / gRPC call — every
    call site reads AppSetting fresh, no cache, no restart (ТЗ §4.21)."""
    setting = db.get(AppSetting, key)
    previous_value = setting.value if setting is not None else None
    if setting is None:
        setting = AppSetting(key=key, value=body.value)
        db.add(setting)
    else:
        setting.value = body.value
    if body.description is not None:
        setting.description = body.description
    setting.updated_by = user.id
    db.flush()
    _audit(
        db,
        user,
        action="admin_update",
        entity_type="AppSetting",
        entity_id=key,
        details={"previous_value": previous_value, "new_value": body.value},
    )
    return AppSettingOut.from_model(setting)


# ---------------------------------------------------------------------
# Integration Export API (defaults + filter schema for admin / VPS UI)
# ---------------------------------------------------------------------


class ExportDefaultsIn(BaseModel):
    default_freshness: str = ""
    default_max_age_hours: int | None = Field(default=None, ge=1, le=168)
    default_limit: int | None = Field(default=None, ge=1, le=100)


class ExportDefaultsOut(BaseModel):
    default_freshness: str = ""
    default_max_age_hours: int | None = None
    default_limit: int | None = None


class ExportIntegrationSettingsOut(BaseModel):
    defaults: ExportDefaultsOut
    filters: list[dict[str, Any]]
    unsupported: list[dict[str, str]]
    implicit_rules: list[dict[str, str]]
    endpoints: dict[str, str]


@router.get("/integration/export-settings", response_model=ExportIntegrationSettingsOut)
def get_integration_export_settings(db: Session = Depends(get_db)) -> ExportIntegrationSettingsOut:
    from common.integration_export_schema import build_export_schema_payload

    payload = build_export_schema_payload(db)
    defaults = payload["defaults"]
    return ExportIntegrationSettingsOut(
        defaults=ExportDefaultsOut(
            default_freshness=defaults.get("default_freshness") or "",
            default_max_age_hours=defaults.get("default_max_age_hours"),
            default_limit=defaults.get("default_limit"),
        ),
        filters=payload["filters"],
        unsupported=payload["unsupported"],
        implicit_rules=payload["implicit_rules"],
        endpoints=payload["endpoints"],
    )


@router.put("/integration/export-settings", response_model=ExportIntegrationSettingsOut)
def upsert_integration_export_settings(
    body: ExportDefaultsIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
) -> ExportIntegrationSettingsOut:
    from common.integration_export_settings import load_export_defaults, save_export_defaults

    previous_defaults = load_export_defaults(db)
    saved = save_export_defaults(
        db,
        default_freshness=body.default_freshness,
        default_max_age_hours=body.default_max_age_hours,
        default_limit=body.default_limit,
        updated_by=user.id,
    )
    db.flush()
    _audit(
        db,
        user,
        action="admin_update",
        entity_type="IntegrationExportSettings",
        entity_id="export_defaults",
        details={"previous": previous_defaults, "new": saved},
    )
    return get_integration_export_settings(db=db)


# ---------------------------------------------------------------------
# Rewrite output locales
# ---------------------------------------------------------------------


class RewriteOutputLocalesIn(BaseModel):
    locales: list[str] = Field(default_factory=lambda: ["ru"])


class RewriteOutputLocalesOut(BaseModel):
    locales: list[str]


@router.get("/rewrite/output-locales", response_model=RewriteOutputLocalesOut)
def get_rewrite_output_locales(db: Session = Depends(get_db)) -> RewriteOutputLocalesOut:
    from common.rewrite_output_locales import get_output_locales

    return RewriteOutputLocalesOut(locales=list(get_output_locales(db)))


@router.put("/rewrite/output-locales", response_model=RewriteOutputLocalesOut)
def upsert_rewrite_output_locales(
    body: RewriteOutputLocalesIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
) -> RewriteOutputLocalesOut:
    from common.rewrite_output_locales import get_output_locales, set_output_locales

    previous = list(get_output_locales(db))
    saved = set_output_locales(db, body.locales, updated_by=user.id)
    db.flush()
    _audit(
        db,
        user,
        action="admin_update",
        entity_type="AppSetting",
        entity_id="rewrite.output_locales",
        details={"previous": previous, "new": list(saved)},
    )
    return RewriteOutputLocalesOut(locales=list(saved))


# ---------------------------------------------------------------------
# Generation working hours
# ---------------------------------------------------------------------


class GenerationDayIn(BaseModel):
    weekday: int = Field(..., ge=0, le=6)
    enabled: bool = True
    start_hour: int = Field(6, ge=0, le=23)
    end_hour: int = Field(18, ge=1, le=24)


class GenerationHoursIn(BaseModel):
    enabled: bool = True
    timezone: str = "Europe/Minsk"
    weekend_daily_limit: int = Field(25, ge=1, le=500)
    days: list[GenerationDayIn] | None = None
    # Legacy flat fields — used when ``days`` is omitted.
    start_hour: int = Field(6, ge=0, le=23)
    end_hour: int = Field(18, ge=1, le=24)
    working_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])


class GenerationDayOut(BaseModel):
    weekday: int
    label: str
    enabled: bool
    start_hour: int
    end_hour: int


class GenerationHoursOut(BaseModel):
    enabled: bool
    timezone: str
    start_hour: int
    end_hour: int
    working_days: list[int]
    weekend_daily_limit: int
    days: list[GenerationDayOut]
    within_hours: bool
    generation_allowed: bool | None = None
    manual_burst: dict | None = None


@router.get("/pipeline/generation-hours", response_model=GenerationHoursOut)
def get_generation_hours(db: Session = Depends(get_db)) -> GenerationHoursOut:
    from common.generation_hours import generation_hours_as_dict, load_generation_hours

    return GenerationHoursOut(**generation_hours_as_dict(load_generation_hours(db), db=db))


@router.put("/pipeline/generation-hours", response_model=GenerationHoursOut)
def upsert_generation_hours(
    body: GenerationHoursIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
) -> GenerationHoursOut:
    from common.generation_hours import (
        DayWindow,
        default_schedule,
        generation_hours_as_dict,
        load_generation_hours,
        save_generation_hours,
    )

    previous = generation_hours_as_dict(load_generation_hours(db), db=db)
    if body.days is not None:
        by_weekday = {d.weekday: d for d in body.days}
        base = list(default_schedule())
        days = []
        for i, fallback in enumerate(base):
            item = by_weekday.get(i)
            if item is None:
                days.append(fallback)
            else:
                days.append(
                    DayWindow(
                        enabled=item.enabled,
                        start_hour=item.start_hour,
                        end_hour=item.end_hour,
                    )
                )
        saved = save_generation_hours(
            db,
            enabled=body.enabled,
            timezone_name=body.timezone,
            days=days,
            weekend_daily_limit=body.weekend_daily_limit,
            updated_by=user.id,
        )
    else:
        saved = save_generation_hours(
            db,
            enabled=body.enabled,
            timezone_name=body.timezone,
            start_hour=body.start_hour,
            end_hour=body.end_hour,
            working_days=body.working_days,
            weekend_daily_limit=body.weekend_daily_limit,
            updated_by=user.id,
        )
    db.flush()
    current = generation_hours_as_dict(saved, db=db)
    _audit(
        db,
        user,
        action="admin_update",
        entity_type="AppSetting",
        entity_id="pipeline.generation_hours",
        details={"previous": previous, "new": current},
    )
    return GenerationHoursOut(**current)


class ManualBurstIn(BaseModel):
    quota: int = Field(25, ge=1, le=200)
    ttl_hours: int = Field(3, ge=1, le=12)


class ManualBurstOut(BaseModel):
    quota: int
    created: int
    remaining: int
    expires_at: str
    requested_at: str | None
    requested_by: str | None
    active: bool


@router.post("/pipeline/manual-burst", response_model=ManualBurstOut)
def start_manual_burst(
    body: ManualBurstIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
) -> ManualBurstOut:
    from common.generation_hours import manual_burst_as_dict, request_manual_burst

    state = request_manual_burst(
        db, quota=body.quota, ttl_hours=body.ttl_hours, requested_by=user.id
    )
    db.flush()
    _audit(
        db,
        user,
        action="admin_update",
        entity_type="AppSetting",
        entity_id="pipeline.manual_generation_burst",
        details={"quota": state.quota, "expires_at": state.expires_at.isoformat()},
    )
    payload = manual_burst_as_dict(db)
    assert payload is not None
    return ManualBurstOut(**payload)


@router.delete("/pipeline/manual-burst")
def stop_manual_burst(
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
) -> dict:
    from common.generation_hours import cancel_manual_burst

    cancel_manual_burst(db, updated_by=user.id)
    db.flush()
    _audit(
        db,
        user,
        action="admin_update",
        entity_type="AppSetting",
        entity_id="pipeline.manual_generation_burst",
        details={"cancelled": True},
    )
    return {"ok": True}


# ---------------------------------------------------------------------
# PromptVersion
# ---------------------------------------------------------------------


class PromptVersionIn(BaseModel):
    template: str
    notes: str | None = None


class PromptVersionOut(BaseModel):
    id: str
    status: str
    notes: str | None
    template: str

    @classmethod
    def from_model(cls, version: PromptVersion) -> PromptVersionOut:
        return cls(
            id=str(version.id),
            status=version.status,
            notes=version.notes,
            template=version.template,
        )


@router.get("/prompt-versions", response_model=list[PromptVersionOut])
def list_prompt_versions(db: Session = Depends(get_db)) -> list[PromptVersionOut]:
    return [PromptVersionOut.from_model(v) for v in db.scalars(select(PromptVersion))]


@router.post(
    "/prompt-versions", response_model=PromptVersionOut, status_code=status.HTTP_201_CREATED
)
def create_prompt_version(
    body: PromptVersionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
) -> PromptVersionOut:
    """Created as draft (ТЗ §4.13) — activate separately once reviewed."""
    version = PromptVersion(
        template=body.template, notes=body.notes, status=PromptVersionStatus.DRAFT
    )
    db.add(version)
    db.flush()
    _audit(
        db,
        user,
        action="admin_create",
        entity_type="PromptVersion",
        entity_id=str(version.id),
        details={"notes": body.notes},
    )
    return PromptVersionOut.from_model(version)


@router.post("/prompt-versions/{version_id}/activate", response_model=PromptVersionOut)
def activate_prompt_version(
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
) -> PromptVersionOut:
    """Activating a version technically retires whichever one is
    currently active — Admin approves the switch, no separate formal
    sign-off process in MVP (ТЗ §4.13)."""
    version = db.get(PromptVersion, version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "prompt version not found")
    currently_active = db.scalars(
        select(PromptVersion).where(PromptVersion.status == PromptVersionStatus.ACTIVE)
    ).all()
    for other in currently_active:
        if other.id != version.id:
            other.status = PromptVersionStatus.RETIRED
    version.status = PromptVersionStatus.ACTIVE
    version.approved_by = user.id
    _audit(
        db,
        user,
        action="admin_activate",
        entity_type="PromptVersion",
        entity_id=str(version.id),
        details={"retired": [str(v.id) for v in currently_active if v.id != version.id]},
    )
    return PromptVersionOut.from_model(version)


# ---------------------------------------------------------------------
# Site categories (theunum.io CMS → tag_category_cache)
# ---------------------------------------------------------------------


class SiteCategoryOut(BaseModel):
    id: str
    slug: str
    name_en: str | None
    name_ru: str | None
    is_active: bool
    synced_at: str

    @classmethod
    def from_model(cls, row: TagCategoryCache) -> SiteCategoryOut:
        return cls(
            id=row.id,
            slug=row.slug,
            name_en=row.name_en,
            name_ru=row.name_ru,
            is_active=row.is_active,
            synced_at=row.synced_at.isoformat(),
        )


@router.get("/site-categories", response_model=list[SiteCategoryOut])
def list_site_categories(db: Session = Depends(get_db)) -> list[SiteCategoryOut]:
    rows = db.scalars(
        select(TagCategoryCache)
        .where(TagCategoryCache.kind == TagCategoryKind.CATEGORY)
        .order_by(TagCategoryCache.slug)
    ).all()
    return [SiteCategoryOut.from_model(row) for row in rows]


@router.post("/site-categories/sync")
def sync_site_categories(
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
) -> dict:
    """Pull categories from api.theunum.io into tag_category_cache."""
    import os

    from api_app.settings import ApiSettings
    from common.site_category_sync import run_theunum_categories_sync

    settings = ApiSettings()
    token = settings.theunum_api_token.strip() or settings.theunum_integration_token.strip()
    if not token:
        token = os.environ.get("THEUNUM_INTEGRATION_TOKEN", "")
    try:
        stats = run_theunum_categories_sync(
            db,
            base_url=settings.theunum_api_base_url,
            path=settings.theunum_categories_path,
            api_token=token,
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    _audit(
        db,
        user,
        action="admin_sync",
        entity_type="TagCategoryCache",
        entity_id="theunum",
        details=stats,
    )
    return stats
