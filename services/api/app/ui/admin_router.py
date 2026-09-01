from __future__ import annotations

import difflib
import uuid
from pathlib import Path

from api_app.auth.dependencies import get_current_user_optional
from api_app.db import get_db
from api_app.routers import admin as admin_api
from common.integration_export_settings import (
    DEFAULT_FRESHNESS_DESCRIPTION,
    DEFAULT_FRESHNESS_KEY,
    DEFAULT_MAX_AGE_HOURS_DESCRIPTION,
    DEFAULT_MAX_AGE_HOURS_KEY,
    load_export_freshness_defaults,
)
from db.app_settings import set_setting
from db.enums import SourceTier
from db.models import User
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

router = APIRouter(prefix="/ui/admin", tags=["ui-admin"])

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _require_admin(user: User | None) -> RedirectResponse | None:
    if user is None:
        return RedirectResponse("/ui/login", status_code=status.HTTP_303_SEE_OTHER)
    if user.role != "admin":
        return RedirectResponse("/ui/drafts", status_code=status.HTTP_303_SEE_OTHER)
    return None


# ---------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------


@router.get("/sources", response_class=HTMLResponse)
def sources_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    redirect = _require_admin(user)
    if redirect:
        return redirect
    sources = admin_api.list_sources(db=db)
    return templates.TemplateResponse(
        request,
        "admin_sources.html",
        {
            "user": user,
            "active": "admin",
            "admin_tab": "sources",
            "sources": sources,
            "tiers": range(1, 7),
        },
    )


@router.post("/sources")
def create_source_ui(
    name: str = Form(...),
    url: str = Form(...),
    tier: int = Form(...),
    language: str = Form("en"),
    poll_interval_seconds: int = Form(900),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    redirect = _require_admin(user)
    if redirect:
        return redirect
    admin_api.create_source(
        admin_api.SourceIn(
            name=name,
            url=url,
            tier=SourceTier(tier),
            language=language,
            poll_interval_seconds=poll_interval_seconds,
        ),
        db=db,
        user=user,
    )
    return RedirectResponse("/ui/admin/sources", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/sources/{source_id}/toggle")
def toggle_source_ui(
    source_id: uuid.UUID,
    is_active: str = Form(...),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    redirect = _require_admin(user)
    if redirect:
        return redirect
    admin_api.update_source(
        source_id, admin_api.SourcePatch(is_active=is_active == "true"), db=db, user=user
    )
    return RedirectResponse("/ui/admin/sources", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------


@router.get("/topics", response_class=HTMLResponse)
def topics_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    redirect = _require_admin(user)
    if redirect:
        return redirect
    topics = admin_api.list_topics(db=db)
    return templates.TemplateResponse(
        request,
        "admin_topics.html",
        {"user": user, "active": "admin", "admin_tab": "topics", "topics": topics},
    )


@router.post("/topics")
def create_topic_ui(
    name: str = Form(...),
    keywords: str = Form(""),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    redirect = _require_admin(user)
    if redirect:
        return redirect
    kw = [k.strip() for k in keywords.split(",") if k.strip()]
    admin_api.create_topic(admin_api.TopicIn(name=name, keywords=kw), db=db, user=user)
    return RedirectResponse("/ui/admin/topics", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/topics/{topic_id}/toggle")
def toggle_topic_ui(
    topic_id: uuid.UUID,
    is_active: str = Form(...),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    redirect = _require_admin(user)
    if redirect:
        return redirect
    admin_api.update_topic(
        topic_id, admin_api.TopicPatch(is_active=is_active == "true"), db=db, user=user
    )
    return RedirectResponse("/ui/admin/topics", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/topics/{topic_id}/keywords")
def update_topic_keywords_ui(
    topic_id: uuid.UUID,
    keywords: str = Form(""),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    redirect = _require_admin(user)
    if redirect:
        return redirect
    kw = [k.strip() for k in keywords.split(",") if k.strip()]
    admin_api.update_topic(topic_id, admin_api.TopicPatch(keywords=kw), db=db, user=user)
    return RedirectResponse("/ui/admin/topics", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------
# LLM rotation models
# ---------------------------------------------------------------------


@router.get("/llm-models", response_class=HTMLResponse)
def llm_models_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    redirect = _require_admin(user)
    if redirect:
        return redirect
    models = admin_api.list_llm_models(db=db)
    return templates.TemplateResponse(
        request,
        "admin_llm_models.html",
        {
            "user": user,
            "active": "admin",
            "admin_tab": "llm-models",
            "models": models,
            "max_active": admin_api.MAX_ACTIVE_LLM_MODELS,
        },
    )


@router.post("/llm-models")
def create_llm_model_ui(
    model_id: str = Form(...),
    position: int = Form(0),
    is_active: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    redirect = _require_admin(user)
    if redirect:
        return redirect
    error = None
    try:
        admin_api.create_llm_model(
            admin_api.LlmModelIn(
                model_id=model_id, position=position, is_active=is_active == "true"
            ),
            db=db,
            user=user,
        )
    except Exception as exc:  # noqa: BLE001
        error = getattr(exc, "detail", str(exc))
    if error:
        return RedirectResponse(
            f"/ui/admin/llm-models?error={error}", status_code=status.HTTP_303_SEE_OTHER
        )
    return RedirectResponse("/ui/admin/llm-models", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/llm-models/{model_id}/toggle")
def toggle_llm_model_ui(
    model_id: uuid.UUID,
    is_active: str = Form(...),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    redirect = _require_admin(user)
    if redirect:
        return redirect
    error = None
    try:
        admin_api.update_llm_model(
            model_id, admin_api.LlmModelPatch(is_active=is_active == "true"), db=db, user=user
        )
    except Exception as exc:  # noqa: BLE001
        error = getattr(exc, "detail", str(exc))
    if error:
        return RedirectResponse(
            f"/ui/admin/llm-models?error={error}", status_code=status.HTTP_303_SEE_OTHER
        )
    return RedirectResponse("/ui/admin/llm-models", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------
# AppSetting
# ---------------------------------------------------------------------


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    redirect = _require_admin(user)
    if redirect:
        return redirect
    settings = admin_api.list_settings(db=db)
    export_freshness, export_max_age_hours = load_export_freshness_defaults(db)
    return templates.TemplateResponse(
        request,
        "admin_settings.html",
        {
            "user": user,
            "active": "admin",
            "admin_tab": "settings",
            "settings": settings,
            "export_freshness": export_freshness or "",
            "export_max_age_hours": export_max_age_hours if export_max_age_hours is not None else "",
        },
    )


@router.post("/settings/export-freshness")
def upsert_export_freshness_ui(
    default_freshness: str = Form(""),
    default_max_age_hours: str = Form(""),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    redirect = _require_admin(user)
    if redirect:
        return redirect

    freshness_value = default_freshness.strip()
    if freshness_value and freshness_value not in ("today", "48h"):
        freshness_value = ""
    set_setting(
        db,
        DEFAULT_FRESHNESS_KEY,
        freshness_value,
        description=DEFAULT_FRESHNESS_DESCRIPTION,
        updated_by=user.id if user else None,
    )

    hours_raw = default_max_age_hours.strip()
    hours_value: str | int = ""
    if hours_raw:
        hours_value = max(1, min(168, int(hours_raw)))
    set_setting(
        db,
        DEFAULT_MAX_AGE_HOURS_KEY,
        hours_value,
        description=DEFAULT_MAX_AGE_HOURS_DESCRIPTION,
        updated_by=user.id if user else None,
    )
    db.commit()
    return RedirectResponse("/ui/admin/settings", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/settings")
def upsert_setting_ui(
    key: str = Form(...),
    value: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    redirect = _require_admin(user)
    if redirect:
        return redirect
    import json

    try:
        parsed = json.loads(value)
    except ValueError:
        parsed = value
    admin_api.upsert_setting(
        key, admin_api.AppSettingIn(value=parsed, description=description or None), db=db, user=user
    )
    return RedirectResponse("/ui/admin/settings", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------
# Prompt versions
# ---------------------------------------------------------------------


@router.get("/prompt-versions", response_class=HTMLResponse)
def prompt_versions_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    redirect = _require_admin(user)
    if redirect:
        return redirect
    versions = admin_api.list_prompt_versions(db=db)
    active_template = next((v.template for v in versions if v.status == "active"), None)
    diffs = {}
    if active_template is not None:
        for v in versions:
            if v.status == "active":
                continue
            diffs[v.id] = "\n".join(
                difflib.unified_diff(
                    active_template.splitlines(),
                    v.template.splitlines(),
                    fromfile="active",
                    tofile="this version",
                    lineterm="",
                )
            )
    return templates.TemplateResponse(
        request,
        "admin_prompt_versions.html",
        {
            "user": user,
            "active": "admin",
            "admin_tab": "prompt-versions",
            "versions": versions,
            "diffs": diffs,
        },
    )


@router.post("/prompt-versions")
def create_prompt_version_ui(
    template: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    redirect = _require_admin(user)
    if redirect:
        return redirect
    admin_api.create_prompt_version(
        admin_api.PromptVersionIn(template=template, notes=notes or None), db=db, user=user
    )
    return RedirectResponse("/ui/admin/prompt-versions", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/prompt-versions/{version_id}/activate")
def activate_prompt_version_ui(
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    redirect = _require_admin(user)
    if redirect:
        return redirect
    admin_api.activate_prompt_version(version_id, db=db, user=user)
    return RedirectResponse("/ui/admin/prompt-versions", status_code=status.HTTP_303_SEE_OTHER)
