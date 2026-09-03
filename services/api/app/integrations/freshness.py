"""Resolve export freshness filters for theunum integration API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

FreshnessPreset = Literal["today", "48h"]


@dataclass(frozen=True)
class ExportTimeCutoffs:
    """Lower bounds applied as AND. 48h is created_at so regen of old news is excluded."""

    content_generated_since: datetime | None = None
    created_since: datetime | None = None


def resolve_export_time_cutoffs(
    *,
    generated_since: datetime | None,
    freshness: FreshnessPreset | None,
    max_age_hours: int | None,
    now: datetime | None = None,
) -> ExportTimeCutoffs:
    generated_cutoffs: list[datetime] = []
    created_cutoffs: list[datetime] = []
    if generated_since is not None:
        ts = generated_since
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        generated_cutoffs.append(ts)

    current = now or datetime.now(UTC)
    if freshness == "today":
        generated_cutoffs.append(current.replace(hour=0, minute=0, second=0, microsecond=0))
    elif freshness == "48h":
        created_cutoffs.append(current - timedelta(hours=48))

    if max_age_hours is not None:
        if max_age_hours < 1:
            raise ValueError("max_age_hours must be >= 1")
        generated_cutoffs.append(current - timedelta(hours=max_age_hours))

    return ExportTimeCutoffs(
        content_generated_since=max(generated_cutoffs) if generated_cutoffs else None,
        created_since=max(created_cutoffs) if created_cutoffs else None,
    )


def resolve_content_generated_since(
    *,
    generated_since: datetime | None,
    freshness: FreshnessPreset | None,
    max_age_hours: int | None,
    now: datetime | None = None,
) -> datetime | None:
    """Lower bound for draft.content_generated_at (today / generated_since / max_age_hours)."""
    return resolve_export_time_cutoffs(
        generated_since=generated_since,
        freshness=freshness,
        max_age_hours=max_age_hours,
        now=now,
    ).content_generated_since
