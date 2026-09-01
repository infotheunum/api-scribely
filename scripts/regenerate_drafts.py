"""Bulk-regenerate existing queue drafts (titles, bodies, SEO, tags).

Re-runs EnrichCluster + RewriteCluster for drafts already in
ready_for_review / needs_fix. Clears draft_export_log so theunum can
re-fetch updated content from Export API.

Each draft ~60-90s of OpenRouter time — use --limit and re-run until
remaining_estimate is 0.

Usage (from repo root, with Postgres + rewrite gRPC reachable):

  cd services/worker && uv run python ../../scripts/regenerate_drafts.py --all --limit 20

Railway (worker service, same env as prod):

  railway run --service worker python scripts/regenerate_drafts.py --all --limit 20
"""

from __future__ import annotations

import argparse
import json
import sys

from db.session import make_engine, make_session_factory
from worker_app.dispatch.regenerate import count_drafts_for_regeneration, run_regenerate_batch
from worker_app.settings import WorkerSettings


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate scribely draft content via LLM")
    parser.add_argument(
        "--all",
        action="store_true",
        help="All ready_for_review + needs_fix (default: only body shorter than 1800 chars)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max drafts per run (default 20 — ~20-40 min OpenRouter time)",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip first N matching drafts (for resuming)",
    )
    parser.add_argument(
        "--keep-export",
        action="store_true",
        help="Do not clear draft_export_log (theunum will NOT see regen in Export API)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print how many drafts match, do not call LLM",
    )
    args = parser.parse_args()

    settings = WorkerSettings()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    db = session_factory()

    try:
        total = count_drafts_for_regeneration(db, all_queue=args.all)
        print(
            f"matching drafts: {total} "
            f"(mode={'all_queue' if args.all else 'short_bodies'}, "
            f"limit={args.limit}, offset={args.offset})"
        )
        if args.dry_run:
            return 0

        if total == 0:
            print("nothing to regenerate")
            return 0

        result = run_regenerate_batch(
            db,
            settings=settings,
            all_queue=args.all,
            limit=args.limit,
            offset=args.offset,
            clear_export=not args.keep_export,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["failed"]:
            return 1
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
