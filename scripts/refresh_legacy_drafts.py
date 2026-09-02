"""Refresh legacy queue drafts without LLM or category sync.

Use when site categories already sync from api.theunum.io, but old drafts
in Postgres still have wall-of-text bodies and/or were already consumed by
theunum Export API.

What it does (per draft in ready_for_review / needs_fix):
  1. Normalize body_en / body_ru to 3 paragraphs separated by \\n\\n
  2. Optionally remap pending_category_slug (--remap invalid|all)
  3. Delete draft_export_log so Export API offers the draft again (default)

Does NOT call OpenRouter. For short bodies (<BODY_MIN_CHARS) use
scripts/regenerate_drafts.py separately.

Usage:
  cd services/worker && uv run python ../../scripts/refresh_legacy_drafts.py --dry-run
  cd services/worker && uv run python ../../scripts/refresh_legacy_drafts.py

Railway (worker or api console — needs DATABASE_URL):
  python scripts/refresh_legacy_drafts.py --dry-run
  python scripts/refresh_legacy_drafts.py
"""

from __future__ import annotations

import argparse
import sys

from common.rewrite_body_format import normalize_body_paragraphs, paragraph_count
from common.rewrite_body_limits import BODY_MIN_CHARS
from common.site_categories import is_valid_site_category_slug, resolve_site_category_slug
from db.enums import DraftStatus
from db.models import Draft, DraftExportLog
from db.session import make_engine, make_session_factory
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from worker_app.settings import WorkerSettings

QUEUE_STATUSES = (DraftStatus.READY_FOR_REVIEW, DraftStatus.NEEDS_FIX)


def _needs_paragraph_refresh(body: str | None) -> bool:
    text = (body or "").strip()
    if not text:
        return False
    return paragraph_count(text) != 3 or "\n\n" not in text


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh legacy drafts (paragraphs + re-export)")
    parser.add_argument("--dry-run", action="store_true", help="Print stats/changes, do not write")
    parser.add_argument(
        "--remap",
        choices=("none", "invalid", "all"),
        default="none",
        help="Remap pending_category_slug: none (default), invalid only, or all drafts",
    )
    parser.add_argument(
        "--no-clear-export",
        action="store_true",
        help="Keep draft_export_log (theunum will NOT see updates in Export API)",
    )
    parser.add_argument(
        "--bodies-only",
        action="store_true",
        help="Only normalize paragraphs; ignore --remap",
    )
    args = parser.parse_args()

    settings = WorkerSettings()
    db = make_session_factory(make_engine(settings.database_url))()
    try:
        drafts = list(
            db.scalars(
                select(Draft)
                .where(Draft.status.in_(QUEUE_STATUSES))
                .options(joinedload(Draft.cluster))
            ).all()
        )

        short_bodies = int(
            db.scalar(
                select(func.count())
                .select_from(Draft)
                .where(Draft.status.in_(QUEUE_STATUSES))
                .where(
                    or_(
                        func.length(Draft.body_en) < BODY_MIN_CHARS,
                        func.length(Draft.body_ru) < BODY_MIN_CHARS,
                    )
                )
            )
            or 0
        )
        null_categories = int(
            db.scalar(
                select(func.count())
                .select_from(Draft)
                .where(Draft.status.in_(QUEUE_STATUSES))
                .where(or_(Draft.pending_category_slug.is_(None), Draft.pending_category_slug == ""))
            )
            or 0
        )
        consumed = int(
            db.scalar(
                select(func.count())
                .select_from(DraftExportLog)
                .join(Draft, Draft.id == DraftExportLog.draft_id)
                .where(Draft.status.in_(QUEUE_STATUSES))
            )
            or 0
        )
        needs_paragraphs = sum(
            1
            for draft in drafts
            if _needs_paragraph_refresh(draft.body_en) or _needs_paragraph_refresh(draft.body_ru)
        )

        print(
            f"queue drafts={len(drafts)} "
            f"needs_paragraphs={needs_paragraphs} "
            f"short_bodies={short_bodies} "
            f"null_category={null_categories} "
            f"already_consumed={consumed}"
        )
        if short_bodies:
            print(
                f"note: {short_bodies} drafts still below {BODY_MIN_CHARS} chars — "
                "run scripts/regenerate_drafts.py after this refresh"
            )

        bodies_changed = 0
        categories_changed = 0
        export_cleared = 0

        for draft in drafts:
            draft_changed = False

            new_en = normalize_body_paragraphs(draft.body_en or "")
            new_ru = normalize_body_paragraphs(draft.body_ru or "")
            if new_en != (draft.body_en or "") or new_ru != (draft.body_ru or ""):
                bodies_changed += 1
                draft_changed = True
                if args.dry_run:
                    print(f"{draft.id}: body paragraphs normalized")
                else:
                    draft.body_en = new_en
                    draft.body_ru = new_ru

            if not args.bodies_only and args.remap != "none":
                old = draft.pending_category_slug
                if args.remap == "invalid" and is_valid_site_category_slug(db, old):
                    pass
                else:
                    hint = " ".join(
                        part
                        for part in (
                            draft.title_en,
                            draft.body_en,
                            draft.title_ru,
                            draft.body_ru,
                            old or "",
                        )
                        if part
                    )
                    new_slug = resolve_site_category_slug(
                        old,
                        db=db,
                        editorial_topic=draft.cluster.topic if draft.cluster else None,
                        hint_text=hint,
                    )
                    if old != new_slug:
                        categories_changed += 1
                        draft_changed = True
                        if args.dry_run:
                            print(f"{draft.id}: category {old!r} -> {new_slug!r}")
                        else:
                            draft.pending_category_slug = new_slug

            if draft_changed and not args.no_clear_export:
                export_log = db.get(DraftExportLog, draft.id)
                if export_log is not None:
                    export_cleared += 1
                    if args.dry_run:
                        print(f"{draft.id}: would clear draft_export_log")
                    else:
                        db.delete(export_log)

        if not args.dry_run:
            db.commit()

        print(
            f"done: bodies_changed={bodies_changed} "
            f"categories_changed={categories_changed} "
            f"export_cleared={export_cleared} dry_run={args.dry_run}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
