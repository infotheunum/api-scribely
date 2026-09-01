from __future__ import annotations

import secrets

from api_app.settings import ApiSettings
from fastapi import Depends, HTTPException, Request, status

INTEGRATION_AUTH_HEADER = "Authorization"
INTEGRATION_TOKEN_HEADER = "X-Theunum-Service-Token"


def _extract_integration_token(request: Request) -> str | None:
    header = request.headers.get(INTEGRATION_TOKEN_HEADER)
    if header:
        return header.strip()
    auth = request.headers.get(INTEGRATION_AUTH_HEADER, "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer ") :].strip()
    return None


def require_integration_token(request: Request) -> None:
    settings = ApiSettings()
    expected = settings.theunum_integration_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="theunum integration is not configured (THEUNUM_INTEGRATION_TOKEN)",
        )
    token = _extract_integration_token(request)
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing integration token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_integration_token_dep(_: None = Depends(require_integration_token)) -> None:
    """FastAPI dependency wrapper."""
