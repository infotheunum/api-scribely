from __future__ import annotations

import logging

from db.enums import DraftStatus
from db.models import Draft
from sqlalchemy import select
from sqlalchemy.orm import Session
from worker_app.compliance.rules import (
    check_forbidden_content,
    has_attribution,
    is_press_release_by_tier,
    matches_disclaimer_trigger,
)
from worker_app.compliance.sensitive import classify_sensitive
from worker_app.compliance.similarity import similarity_gate_triggered

logger = logging.getLogger(__name__)


def _draft_text(draft: Draft) -> str:
    return " ".join([draft.title_en, draft.body_en, draft.title_ru, draft.body_ru])


def _gate_draft(db: Session, draft: Draft) -> None:
    cluster = draft.cluster
    notes: list[str] = []
    blocked = False
    needs_fix = False

    if is_press_release_by_tier(cluster) and not draft.press_release_flag:
        draft.press_release_flag = True
        notes.append("press_release: Уровень 6 источник в кластере (rule override)")

    if not has_attribution(draft):
        notes.append("missing attribution")
        needs_fix = True

    forbidden_hits = check_forbidden_content(_draft_text(draft))
    if forbidden_hits:
        notes.append(f"forbidden content: {', '.join(forbidden_hits)}")
        blocked = True

    if not draft.disclaimer_flag and matches_disclaimer_trigger(_draft_text(draft)):
        draft.disclaimer_flag = True
        notes.append("disclaimer: rule-based trigger")

    triggered, score = similarity_gate_triggered(db, cluster, draft)
    draft.similarity_score = score
    if triggered:
        notes.append(f"similarity-to-source gate triggered ({score:.2f})")
        needs_fix = True

    if draft.fact_conflict:
        notes.append("fact_conflict from enrichment — сверить факты")
        needs_fix = True

    sensitive_categories = classify_sensitive(_draft_text(draft))
    if sensitive_categories:
        draft.sensitive_hold = True
        notes.append(f"sensitive_hold: {', '.join(sensitive_categories)}")

    draft.compliance_notes = notes

    if blocked:
        # ТЗ §11.4 — stays in DRAFTING (never promoted to the review
        # queue) until a human resolves it manually; no override path
        # exists yet since that's queue/review UI (Фаза 6).
        draft.status = DraftStatus.DRAFTING
    elif needs_fix:
        draft.status = DraftStatus.NEEDS_FIX
    else:
        draft.status = DraftStatus.READY_FOR_REVIEW


def run_compliance_cycle(db: Session) -> dict:
    """Gates every freshly-dispatched Draft (Фаза 4 leaves them in
    DRAFTING) through the rule-based Policy/Compliance Checker (ТЗ §4.6,
    §4.20) before it can reach READY_FOR_REVIEW. Runs after dispatch in
    the same scheduler tick so a Draft doesn't sit ungated until the
    next cycle."""
    drafts = db.scalars(select(Draft).where(Draft.status == DraftStatus.DRAFTING)).all()
    stats = {"reviewed": 0, "ready": 0, "needs_fix": 0, "blocked": 0, "sensitive_hold": 0}
    for draft in drafts:
        previous_status = draft.status
        _gate_draft(db, draft)
        stats["reviewed"] += 1
        if draft.status == DraftStatus.READY_FOR_REVIEW:
            stats["ready"] += 1
        elif draft.status == DraftStatus.NEEDS_FIX:
            stats["needs_fix"] += 1
        elif draft.status == DraftStatus.DRAFTING and previous_status == DraftStatus.DRAFTING:
            stats["blocked"] += 1
        if draft.sensitive_hold:
            stats["sensitive_hold"] += 1
    db.commit()
    return stats
