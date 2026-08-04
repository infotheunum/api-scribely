from __future__ import annotations

import uuid
from typing import Any

from api_app.auth.dependencies import require_role
from api_app.db import get_db
from common.tracing import get_trace_id
from db.enums import PromptVersionStatus, SourceTier, SourceType
from db.models import AppSetting, AuditLog, LlmRotationModel, PromptVersion, Source, Topic, User
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
    return [SourceOut.from_model(s) for s in db.scalars(select(Source))]


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
    if source is None:
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
