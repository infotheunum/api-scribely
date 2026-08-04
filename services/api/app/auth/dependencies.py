from __future__ import annotations

import uuid

import jwt
from api_app.auth.security import decode_access_token
from api_app.db import get_db
from api_app.settings import ApiSettings
from db.models import User
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

# Browser session cookie for the Review UI (ТЗ §6.3) — the JWT-issuing
# API auth (/auth/login, Bearer header) is untouched; the UI just stores
# the same token in an httponly cookie instead of a client-side JS
# fetch header, since this is server-rendered Jinja2/HTMX, not an SPA.
# Both forms decode through the exact same JWT — a single set of
# /drafts, /admin, etc. JSON endpoints serves API clients (header) and
# the HTMX-driven UI (cookie) without duplicate routes.
UI_COOKIE_NAME = "access_token"


def _extract_token(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[len("Bearer ") :]
    return request.cookies.get(UI_COOKIE_NAME)


def _decode_user(token: str, db: Session) -> User | None:
    settings = ApiSettings()
    try:
        payload = decode_access_token(
            token, secret=settings.jwt_secret, algorithm=settings.jwt_algorithm
        )
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _extract_token(request)
    user = _decode_user(token, db) if token else None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(*roles: str):
    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role")
        return user

    return _check


def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Never raises — UI page routes (not the JSON API) use this and
    redirect to /ui/login themselves on None, instead of a raw 401."""
    token = _extract_token(request)
    return _decode_user(token, db) if token else None
