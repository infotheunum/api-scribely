"""Remap pending_category_slug on existing drafts to theunum site categories.

Does not call LLM — uses cluster.topic + title/body heuristics.
Does not fetch categories from api.theunum.io — uses bootstrap list in
Postgres (crypto, economics, finance, technology, world, ai).

Usage:
  cd services/worker && uv run python ../../scripts/remap_draft_categories.py --dry-run
  cd services/worker && uv run python ../../scripts/remap_draft_categories.py --invalid-only
  cd services/worker && uv run python ../../scripts/remap_draft_categories.py --invalid-only --clear-export

Railway:
  railway run --service worker python scripts/remap_draft_categories.py --invalid-only --clear-export
"""

from __future__ import annotations

import argparse
import sys

from db.enums import DraftStatus
from db.models import Draft, DraftExportLog
from db.session import make_engine, make_session_factory
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from common.site_categories import bootstrap_site_categories_if_empty, is_valid_site_category_slug, resolve_site_category_slug
from worker_app.settings import WorkerSettings

QUEUE_STATUSES = (DraftStatus.READY_FOR_REVIEW, DraftStatus.NEEDS_FIX)


def main() -> int:
    parser = argparse.ArgumentParser(description="Remap draft pending_category_slug to site categories")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    parser.add_argument(
        "--invalid-only",
        action="store_true",
        help="Only drafts whose current slug is missing or not in the allowed CMS list",
    )
    parser.add_argument(
        "--clear-export",
        action="store_true",
        help="Delete draft_export_log for changed drafts (theunum Export API will re-offer them)",
    )
    args = parser.parse_args()

    settings = WorkerSettings()
    db = make_session_factory(make_engine(settings.database_url))()
    try:
        bootstrap_site_categories_if_empty(db)
        db.commit()

        drafts = list(
            db.scalars(
                select(Draft)
                .where(Draft.status.in_(QUEUE_STATUSES))
                .options(joinedload(Draft.cluster))
            ).all()
        )
        changed = 0
        skipped_valid = 0
        for draft in drafts:
            old = draft.pending_category_slug
            if args.invalid_only and is_valid_site_category_slug(db, old):
                skipped_valid += 1
                continue

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
            new = resolve_site_category_slug(
                old,
                db=db,
                editorial_topic=draft.cluster.topic if draft.cluster else None,
                hint_text=hint,
            )
            if old != new:
                changed += 1
                print(f"{draft.id}: {old!r} -> {new!r}")
                if not args.dry_run:
                    draft.pending_category_slug = new
                    if args.clear_export:
                        export_log = db.get(DraftExportLog, draft.id)
                        if export_log is not None:
                            db.delete(export_log)
            elif args.invalid_only and not is_valid_site_category_slug(db, old):
                # Resolved to same invalid slug shouldn't happen; log if it does.
                print(f"{draft.id}: still invalid {old!r} (no change)")

        if not args.dry_run:
            db.commit()
        print(
            f"scanned={len(drafts)} changed={changed} "
            f"skipped_valid={skipped_valid if args.invalid_only else 'n/a'}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
