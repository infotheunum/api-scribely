from __future__ import annotations

from datetime import UTC, datetime

from common.generation_stats import build_generation_stats, resolve_period
from db.enums import DraftStatus, QuarantineReason, SourceTier, SourceType
from db.models import AuditLog, ClusterQuarantine, Draft, NewsCluster, Source


def _auth_headers(client, user):
    resp = client.post(
        "/auth/login", data={"username": user.username, "password": "correct-horse-battery-staple"}
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_resolve_period_today():
    now = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    start, end, label = resolve_period("today", now=now)
    assert label == "today"
    assert end == now
    assert start < end


def test_build_generation_stats_funnel(clean_db):
    source = Source(
        name="S",
        url="https://example.com/feed",
        type=SourceType.RSS,
        tier=SourceTier.TIER_1,
        language="en",
    )
    c1 = NewsCluster(trace_id="ok")
    c2 = NewsCluster(trace_id="bad")
    clean_db.add_all([source, c1, c2])
    clean_db.flush()
    clean_db.add(
        Draft(
            cluster_id=c1.id,
            status=DraftStatus.READY_FOR_REVIEW,
            title_en="t",
            body_en="b",
            title_ru="т",
            body_ru="т",
            trace_id="ok",
        )
    )
    clean_db.add(
        ClusterQuarantine(
            cluster_id=c2.id,
            reason=QuarantineReason.FACTUAL_VERIFICATION_FAILED,
            evidence="gate",
        )
    )
    clean_db.add(
        AuditLog(
            action="publish",
            entity_type="Draft",
            entity_id=str(c1.id),
            details={},
        )
    )
    clean_db.add(
        AuditLog(
            action="reject",
            entity_type="Draft",
            entity_id="x",
            details={"reason": "low_quality"},
        )
    )
    clean_db.commit()

    stats = build_generation_stats(clean_db, period="today")
    assert stats["funnel"]["drafts_created"] == 1
    assert stats["funnel"]["quality_gate_rejected"] == 1
    assert stats["funnel"]["editor_published"] == 1
    assert stats["funnel"]["editor_rejected"] == 1
    assert stats["funnel"]["attempted_rewrite"] == 2
    assert stats["queue_now"]["ready_for_review"] == 1
    assert "llm_tokens" in stats


def test_admin_api_generation_stats(client, admin_user, clean_db):
    resp = client.get(
        "/admin/pipeline/generation-stats?period=today",
        headers=_auth_headers(client, admin_user),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "funnel" in body
    assert "drafts_created" in body["funnel"]


def test_admin_ui_generation_stats_page(client, admin_user, clean_db):
    page = client.get(
        "/ui/admin/generation-stats?period=7d",
        headers=_auth_headers(client, admin_user),
    )
    assert page.status_code == 200
    assert "Воронка" in page.text
