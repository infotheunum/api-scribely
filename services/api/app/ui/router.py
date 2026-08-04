from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from api_app.auth.dependencies import UI_COOKIE_NAME, get_current_user_optional
from api_app.auth.security import create_access_token, verify_password
from api_app.db import get_db
from api_app.routers import drafts as drafts_api
from api_app.settings import ApiSettings
from common.fulltext import fetch_full_text
from common.tracing import get_trace_id
from db.enums import DraftStatus, RejectReason, SourceType
from db.models import Draft, RawItem, Source, User
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/ui", tags=["ui"])

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

REJECT_REASONS = [r.value for r in RejectReason]


def _require_login(request: Request, user: User | None) -> RedirectResponse | None:
    if user is None:
        return RedirectResponse(
            f"/ui/login?next={request.url.path}", status_code=status.HTTP_303_SEE_OTHER
        )
    return None


# ---------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str | None = None) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {"user": None, "error": error})


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    settings = ApiSettings()
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"user": None, "error": "Неверный логин или пароль"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    token = create_access_token(
        user_id=user.id,
        role=user.role,
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_minutes=settings.jwt_expire_minutes,
    )
    resp = RedirectResponse("/ui/drafts", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(
        UI_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        max_age=settings.jwt_expire_minutes * 60,
    )
    return resp


@router.get("/logout")
def logout():
    resp = RedirectResponse("/ui/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(UI_COOKIE_NAME)
    return resp


# ---------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------


@router.get("/drafts", response_class=HTMLResponse)
def queue_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    redirect = _require_login(request, user)
    if redirect:
        return redirect

    summaries = drafts_api.list_drafts(status_filter=None, db=db, _user=user)

    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    published_today_count = len(
        db.scalars(
            select(Draft).where(
                Draft.status == DraftStatus.PUBLISHED, Draft.updated_at >= today_start
            )
        ).all()
    )

    return templates.TemplateResponse(
        request,
        "queue.html",
        {
            "user": user,
            "active": "queue",
            "drafts": summaries,
            "published_today": published_today_count,
        },
    )


@router.get("/drafts/next")
def next_draft(
    after: uuid.UUID,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    if user is None:
        return RedirectResponse("/ui/login", status_code=status.HTTP_303_SEE_OTHER)
    summaries = drafts_api.list_drafts(status_filter=None, db=db, _user=user)
    ids = [s.id for s in summaries]
    try:
        idx = ids.index(str(after))
    except ValueError:
        idx = -1
    remaining = [i for i in ids if i != str(after)]
    if idx >= 0 and idx + 1 < len(ids) and ids[idx + 1] != str(after):
        target = ids[idx + 1]
    elif remaining:
        target = remaining[0]
    else:
        return RedirectResponse("/ui/drafts", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(f"/ui/drafts/{target}", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------
# Draft detail + actions
# ---------------------------------------------------------------------


@router.get("/drafts/{draft_id}", response_class=HTMLResponse)
def draft_detail_page(
    request: Request,
    draft_id: uuid.UUID,
    saved: bool = False,
    error: str | None = None,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    redirect = _require_login(request, user)
    if redirect:
        return redirect

    detail = drafts_api.get_draft(draft_id, db=db, _user=user)
    return templates.TemplateResponse(
        request,
        "draft_detail.html",
        {
            "user": user,
            "active": "queue",
            "draft": detail,
            "reject_reasons": REJECT_REASONS,
            "saved": saved,
            "error": error,
            "lock": None,
            "viewer_count": 1,
        },
    )


@router.post("/drafts/{draft_id}/save")
def save_draft(
    request: Request,
    draft_id: uuid.UUID,
    version: int = Form(...),
    title_en: str = Form(""),
    body_en: str = Form(""),
    title_ru: str = Form(""),
    body_ru: str = Form(""),
    seo_title_en: str = Form(""),
    seo_description_en: str = Form(""),
    slug_en: str = Form(""),
    focus_keyphrase_en: str = Form(""),
    keywords_en: str = Form(""),
    seo_title_ru: str = Form(""),
    seo_description_ru: str = Form(""),
    slug_ru: str = Form(""),
    focus_keyphrase_ru: str = Form(""),
    keywords_ru: str = Form(""),
    image_brief: str = Form(""),
    image_mood: str = Form(""),
    image_style: str = Form(""),
    image_alt: str = Form(""),
    image_caption: str = Form(""),
    image_license_confirmed: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    if user is None:
        return RedirectResponse("/ui/login", status_code=status.HTTP_303_SEE_OTHER)

    patch = drafts_api.DraftPatch(
        version=version,
        title_en=title_en,
        body_en=body_en,
        title_ru=title_ru,
        body_ru=body_ru,
        seo_title_en=seo_title_en,
        seo_description_en=seo_description_en,
        slug_en=slug_en,
        focus_keyphrase_en=focus_keyphrase_en,
        keywords_en=[k.strip() for k in keywords_en.split(",") if k.strip()],
        seo_title_ru=seo_title_ru,
        seo_description_ru=seo_description_ru,
        slug_ru=slug_ru,
        focus_keyphrase_ru=focus_keyphrase_ru,
        keywords_ru=[k.strip() for k in keywords_ru.split(",") if k.strip()],
        image_brief=image_brief,
        image_mood=image_mood,
        image_style=image_style,
        image_alt=image_alt,
        image_caption=image_caption,
        image_license_confirmed=image_license_confirmed == "true",
    )
    try:
        drafts_api.patch_draft(draft_id, patch, db=db, user=user)
    except Exception as exc:  # noqa: BLE001 — surfaced to the human as a page error, not a 500
        detail = getattr(exc, "detail", str(exc))
        return RedirectResponse(
            f"/ui/drafts/{draft_id}?error={detail}", status_code=status.HTTP_303_SEE_OTHER
        )
    return RedirectResponse(f"/ui/drafts/{draft_id}?saved=1", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/drafts/{draft_id}/publish")
def publish_draft_ui(
    draft_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    if user is None:
        return RedirectResponse("/ui/login", status_code=status.HTTP_303_SEE_OTHER)
    try:
        drafts_api.publish_draft(draft_id, db=db, user=user)
    except Exception as exc:  # noqa: BLE001
        detail = getattr(exc, "detail", str(exc))
        return RedirectResponse(
            f"/ui/drafts/{draft_id}?error={detail}", status_code=status.HTTP_303_SEE_OTHER
        )
    return RedirectResponse("/ui/drafts", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/drafts/{draft_id}/reject")
def reject_draft_ui(
    draft_id: uuid.UUID,
    reason: RejectReason = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    if user is None:
        return RedirectResponse("/ui/login", status_code=status.HTTP_303_SEE_OTHER)
    drafts_api.reject_draft(
        draft_id, drafts_api.ActionReasonBody(reason=reason, note=note or None), db=db, user=user
    )
    return RedirectResponse("/ui/drafts", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/drafts/{draft_id}/needs-fix")
def needs_fix_draft_ui(
    draft_id: uuid.UUID,
    reason: RejectReason = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    if user is None:
        return RedirectResponse("/ui/login", status_code=status.HTTP_303_SEE_OTHER)
    drafts_api.needs_fix_draft(
        draft_id, drafts_api.ActionReasonBody(reason=reason, note=note or None), db=db, user=user
    )
    return RedirectResponse("/ui/drafts", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/drafts/{draft_id}/snooze")
def snooze_draft_ui(
    draft_id: uuid.UUID,
    note: str = Form(""),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    if user is None:
        return RedirectResponse("/ui/login", status_code=status.HTTP_303_SEE_OTHER)
    drafts_api.snooze_draft(draft_id, drafts_api.SnoozeBody(note=note or None), db=db, user=user)
    return RedirectResponse("/ui/drafts", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------
# Manual inject URL (ТЗ §4.1) — form on top of the existing API endpoint
# ---------------------------------------------------------------------


@router.get("/inject", response_class=HTMLResponse)
def inject_page(
    request: Request,
    created: bool | None = None,
    error: str | None = None,
    user: User | None = Depends(get_current_user_optional),
):
    redirect = _require_login(request, user)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request,
        "inject.html",
        {"user": user, "active": "inject", "created": created, "error": error},
    )


@router.post("/inject")
def inject_submit(
    url: str = Form(...),
    title: str = Form(""),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    if user is None:
        return RedirectResponse("/ui/login", status_code=status.HTTP_303_SEE_OTHER)

    source = db.scalar(select(Source).where(Source.type == SourceType.MANUAL))
    if source is None:
        return RedirectResponse(
            "/ui/inject?error=Источник+для+ручного+добавления+не+настроен",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    existing = db.scalar(
        select(RawItem).where(RawItem.source_id == source.id, RawItem.external_id == url)
    )
    if existing is not None:
        return RedirectResponse("/ui/inject?created=0", status_code=status.HTTP_303_SEE_OTHER)

    full_text = fetch_full_text(url)
    db.add(
        RawItem(
            source_id=source.id,
            external_id=url,
            url=url,
            title=title or url,
            body=full_text,
            is_full_text=full_text is not None,
            language=source.language,
            is_manual_inject=True,
            trace_id=get_trace_id(),
        )
    )
    db.flush()
    return RedirectResponse("/ui/inject?created=1", status_code=status.HTTP_303_SEE_OTHER)
