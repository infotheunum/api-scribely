"""Fact-check the active editorial queue and quarantine failed drafts.

Run from the worker environment, first without --apply:

  cd services/worker && uv run python ../../scripts/audit_active_drafts.py --limit 20
  cd services/worker && uv run python ../../scripts/audit_active_drafts.py --limit 20 --apply
"""

from __future__ import annotations

import argparse
import json
import sys

from db.enums import DraftStatus, QuarantineReason
from db.models import ClusterQuarantine, Draft
from db.session import make_engine, make_session_factory
from rewrite_app.rewrite.orchestrator import _quality_required_facts
from rewrite_app.rewrite.quality_gate import review_rewrite
from worker_app.settings import WorkerSettings
from sqlalchemy import select


def _sources_text(draft: Draft) -> str:
    return "\n\n".join(
        f"[{item.title}] ({item.source.name}, {item.language}, {item.url})\n"
        f"{item.body or item.title}"
        for item in draft.cluster.raw_items
    )


def _facts_text(draft: Draft) -> str:
    context = draft.cluster.context
    if context is None or not context.facts:
        return "(нет)"
    return "\n".join(
        f"- [{fact.get('kind', 'what')}] {fact.get('text', '')}" for fact in context.facts
    )


def _rewritten_text(draft: Draft) -> str:
    return json.dumps(
        {
            "title_en": draft.title_en,
            "body_en": draft.body_en,
            "title_ru": draft.title_ru,
            "body_ru": draft.body_ru,
            "seo_title_en": draft.seo_title_en,
            "seo_description_en": draft.seo_description_en,
            "seo_title_ru": draft.seo_title_ru,
            "seo_description_ru": draft.seo_description_ru,
            "keywords_en": draft.keywords_en,
            "keywords_ru": draft.keywords_ru,
        },
        ensure_ascii=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit active drafts with the factual quality gate")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--apply", action="store_true", help="quarantine failed drafts")
    args = parser.parse_args()
    settings = WorkerSettings()
    db = make_session_factory(make_engine(settings.database_url))()
    try:
        drafts = db.scalars(
            select(Draft)
            .where(Draft.status.in_((DraftStatus.READY_FOR_REVIEW, DraftStatus.NEEDS_FIX)))
            .order_by(Draft.created_at)
            .limit(args.limit)
        ).all()
        failed = 0
        for draft in drafts:
            approved, issues, _, _, _, _ = review_rewrite(
                db,
                settings,
                sources_text=_sources_text(draft),
                required_facts_text=_quality_required_facts(_facts_text(draft)),
                rewritten_text=_rewritten_text(draft),
                translate_sources=False,
            )
            if approved:
                print(f"PASS {draft.id}")
                continue
            failed += 1
            evidence = "; ".join(issues)[:4000]
            print(f"FAIL {draft.id}: {evidence}")
            if not args.apply:
                continue
            row = db.scalar(
                select(ClusterQuarantine).where(ClusterQuarantine.cluster_id == draft.cluster_id)
            )
            if row is None:
                db.add(
                    ClusterQuarantine(
                        cluster_id=draft.cluster_id,
                        reason=QuarantineReason.FACTUAL_VERIFICATION_FAILED,
                        evidence=evidence,
                    )
                )
            else:
                row.reason = QuarantineReason.FACTUAL_VERIFICATION_FAILED
                row.evidence = evidence
                row.released_at = None
                row.released_by = None
            draft.status = DraftStatus.REJECTED
        if args.apply:
            db.commit()
        print(json.dumps({"scanned": len(drafts), "failed": failed, "applied": args.apply}))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
