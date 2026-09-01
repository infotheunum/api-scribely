from __future__ import annotations

from datetime import UTC, datetime

from common.integration_reasons import REASON_OK, classify_openrouter_message
from db.app_settings import set_setting
from sqlalchemy.orm import Session

KEY_LAST_ERROR_CODE = "pipeline.last_error_code"
KEY_LAST_ERROR_MESSAGE = "pipeline.last_error_message"
KEY_LAST_ERROR_AT = "pipeline.last_error_at"
KEY_LAST_DISPATCH_AT = "pipeline.last_dispatch_at"
KEY_LAST_DISPATCH_DISPATCHED = "pipeline.last_dispatch_dispatched"
KEY_LAST_DISPATCH_FAILED = "pipeline.last_dispatch_failed"


def record_dispatch_cycle_result(
    db: Session,
    *,
    dispatched: int,
    failed: int,
    last_error_message: str | None = None,
) -> None:
    """Persist the latest worker dispatch tick for theunum integrations API."""
    now = datetime.now(UTC).isoformat()
    set_setting(db, KEY_LAST_DISPATCH_AT, now)
    set_setting(db, KEY_LAST_DISPATCH_DISPATCHED, dispatched)
    set_setting(db, KEY_LAST_DISPATCH_FAILED, failed)

    if failed > 0 and last_error_message:
        code = classify_openrouter_message(last_error_message)
        set_setting(db, KEY_LAST_ERROR_CODE, code)
        set_setting(db, KEY_LAST_ERROR_MESSAGE, last_error_message)
        set_setting(db, KEY_LAST_ERROR_AT, now)
    elif dispatched > 0:
        set_setting(db, KEY_LAST_ERROR_CODE, REASON_OK)
        set_setting(db, KEY_LAST_ERROR_MESSAGE, "")
        set_setting(db, KEY_LAST_ERROR_AT, now)
    db.commit()
