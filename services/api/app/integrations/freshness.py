"""Resolve export freshness filters for theunum integration API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

FreshnessPreset = Literal["today", "48h"]


def resolve_content_generated_since(
    *,
    generated_since: datetime | None,
    freshness: FreshnessPreset | None,
    max_age_hours: int | None,
    now: datetime | None = None,
) -> datetime | None:
    """Return the effective lower bound for draft.content_generated_at."""
    cutoffs: list[datetime] = []
    if generated_since is not None:
        ts = generated_since
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        cutoffs.append(ts)

    current = now or datetime.now(UTC)
    if freshness == "today":
        cutoffs.append(current.replace(hour=0, minute=0, second=0, microsecond=0))
    elif freshness == "48h":
        cutoffs.append(current - timedelta(hours=48))

    if max_age_hours is not None:
        if max_age_hours < 1:
            raise ValueError("max_age_hours must be >= 1")
        cutoffs.append(current - timedelta(hours=max_age_hours))

    if not cutoffs:
        return None
    return max(cutoffs)
