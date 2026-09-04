from __future__ import annotations

from db.enums import DraftStatus, SourceTier, SourceType
from db.models import Draft, NewsCluster, RawItem, Source


def _auth_headers(client, user):
    resp = client.post(
        "/auth/login", data={"username": user.username, "password": "correct-horse-battery-staple"}
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _source(db) -> Source:
    source = Source(
        name="Test Wire",
        url="https://example.com/feed",
        type=SourceType.RSS,
        tier=SourceTier.TIER_1,
        language="en",
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _cluster(db, source) -> NewsCluster:
    cluster = NewsCluster(trace_id="t", topic="Криптовалюты и цифровые активы")
    db.add(cluster)
    db.commit()
    db.add(
        RawItem(
            source_id=source.id,
            external_id=f"item-{cluster.id}",
            url=f"https://example.com/{cluster.id}",
            title="Original headline",
            body="Original body text.",
            language="en",
            trace_id="t",
            cluster_id=cluster.id,
        )
    )
    db.commit()
    db.refresh(cluster)
    return cluster


def _draft(db, cluster, **overrides) -> Draft:
    defaults = dict(
        cluster_id=cluster.id,
        title_en="Bitcoin rallies on ETF inflows",
        body_en="x" * 150,
        title_ru="y" * 20,
        body_ru="y" * 150,
        attribution_urls=["https://example.com/a"],
        trace_id="t",
        status=DraftStatus.READY_FOR_REVIEW,
        image_license_confirmed=False,
    )
    defaults.update(overrides)
    draft = Draft(**defaults)
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def test_list_drafts_requires_auth(client, clean_db):
    resp = client.get("/drafts")
    assert resp.status_code == 401


def test_list_drafts_defaults_to_ready_and_needs_fix(client, test_user, clean_db):
    source = _source(clean_db)
    cluster1 = _cluster(clean_db, source)
    cluster2 = _cluster(clean_db, source)
    cluster3 = _cluster(clean_db, source)
    ready = _draft(clean_db, cluster1, status=DraftStatus.READY_FOR_REVIEW)
    needs_fix = _draft(clean_db, cluster2, status=DraftStatus.NEEDS_FIX)
    _draft(clean_db, cluster3, status=DraftStatus.PUBLISHED)

    resp = client.get("/drafts", headers=_auth_headers(client, test_user))
    assert resp.status_code == 200
    ids = {d["id"] for d in resp.json()}
    assert ids == {str(ready.id), str(needs_fix.id)}


def test_list_drafts_sorts_flagged_first(client, test_user, clean_db):
    source = _source(clean_db)
    cluster1 = _cluster(clean_db, source)
    cluster2 = _cluster(clean_db, source)
    clean = _draft(clean_db, cluster1, status=DraftStatus.READY_FOR_REVIEW)
    flagged = _draft(clean_db, cluster2, status=DraftStatus.READY_FOR_REVIEW, sensitive_hold=True)

    resp = client.get("/drafts", headers=_auth_headers(client, test_user))
    ids_in_order = [d["id"] for d in resp.json()]
    assert ids_in_order.index(str(flagged.id)) < ids_in_order.index(str(clean.id))


def test_list_drafts_sorts_newest_first_within_group(client, test_user, clean_db):
    from datetime import UTC, datetime, timedelta

    source = _source(clean_db)
    older = _draft(clean_db, _cluster(clean_db, source), status=DraftStatus.READY_FOR_REVIEW)
    newer = _draft(clean_db, _cluster(clean_db, source), status=DraftStatus.READY_FOR_REVIEW)
    older.created_at = datetime.now(UTC) - timedelta(days=7)
    newer.created_at = datetime.now(UTC)
    clean_db.commit()

    resp = client.get("/drafts", headers=_auth_headers(client, test_user))
    ids_in_order = [d["id"] for d in resp.json()]
    assert ids_in_order.index(str(newer.id)) < ids_in_order.index(str(older.id))


def test_get_draft_detail_includes_sources(client, test_user, clean_db):
    from common.rewrite_body_format import normalize_body_paragraphs

    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    draft = _draft(clean_db, cluster)

    resp = client.get(f"/drafts/{draft.id}", headers=_auth_headers(client, test_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["body_en"] == normalize_body_paragraphs(draft.body_en)
    assert len(body["sources"]) == 1
    assert body["sources"][0]["source_name"] == "Test Wire"
    assert body["sources"][0]["body"] == "Original body text."
    assert body["sources"][0]["url"].startswith("https://example.com/")
    assert body["sources"][0]["is_full_text"] is False


def test_get_draft_404(client, test_user, clean_db):
    resp = client.get(
        "/drafts/00000000-0000-0000-0000-000000000000", headers=_auth_headers(client, test_user)
    )
    assert resp.status_code == 404


def test_patch_draft_updates_and_bumps_version(client, test_user, clean_db):
    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    draft = _draft(clean_db, cluster)

    resp = client.patch(
        f"/drafts/{draft.id}",
        json={"version": draft.version, "title_en": "Edited title"},
        headers=_auth_headers(client, test_user),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title_en"] == "Edited title"
    assert body["version"] == draft.version + 1


def test_patch_draft_rejects_stale_version(client, test_user, clean_db):
    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    draft = _draft(clean_db, cluster)

    resp = client.patch(
        f"/drafts/{draft.id}",
        json={"version": draft.version + 5, "title_en": "Edited title"},
        headers=_auth_headers(client, test_user),
    )
    assert resp.status_code == 409


def test_publish_requires_image_license_confirmed(client, test_user, clean_db):
    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    draft = _draft(clean_db, cluster, image_license_confirmed=False)

    resp = client.post(f"/drafts/{draft.id}/publish", headers=_auth_headers(client, test_user))
    assert resp.status_code == 400


def test_publish_succeeds_once_license_confirmed(client, test_user, clean_db):
    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    draft = _draft(clean_db, cluster, image_license_confirmed=True)

    resp = client.post(f"/drafts/{draft.id}/publish", headers=_auth_headers(client, test_user))
    assert resp.status_code == 200
    assert resp.json()["status"] == "published"


def test_publish_resolves_pending_tags_and_records_publish_record(client, test_user, clean_db):
    from db.models import PublishRecord

    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    draft = _draft(
        clean_db,
        cluster,
        image_license_confirmed=True,
        pending_tags=[{"slug": "bitcoin", "name": "Bitcoin"}],
        pending_category_slug="markets",
    )

    resp = client.post(f"/drafts/{draft.id}/publish", headers=_auth_headers(client, test_user))
    assert resp.status_code == 200

    clean_db.refresh(draft)
    assert draft.category_id == "mock-category-markets"
    assert draft.tag_ids == ["mock-tag-bitcoin"]

    record = clean_db.query(PublishRecord).filter_by(draft_id=draft.id).one()
    assert record.category_id == "mock-category-markets"
    assert record.tag_ids == ["mock-tag-bitcoin"]
    assert record.published_by == test_user.id


def test_publish_snapshots_human_final_revision(client, test_user, clean_db):
    from db.enums import DraftRevisionKind
    from db.models import DraftRevision

    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    draft = _draft(clean_db, cluster, image_license_confirmed=True)

    client.post(f"/drafts/{draft.id}/publish", headers=_auth_headers(client, test_user))

    revision = (
        clean_db.query(DraftRevision)
        .filter_by(draft_id=draft.id, kind=DraftRevisionKind.HUMAN_FINAL)
        .one()
    )
    assert revision.title_en == draft.title_en
    assert revision.author_id == test_user.id


def test_reject_requires_reason_enum(client, test_user, clean_db):
    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    draft = _draft(clean_db, cluster)

    bad = client.post(
        f"/drafts/{draft.id}/reject",
        json={"reason": "not_a_real_reason"},
        headers=_auth_headers(client, test_user),
    )
    assert bad.status_code == 422

    good = client.post(
        f"/drafts/{draft.id}/reject",
        json={"reason": "low_quality", "note": "weak lede"},
        headers=_auth_headers(client, test_user),
    )
    assert good.status_code == 200
    assert good.json()["status"] == "rejected"


def test_needs_fix_requires_reason_enum(client, test_user, clean_db):
    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    draft = _draft(clean_db, cluster)

    resp = client.post(
        f"/drafts/{draft.id}/needs-fix",
        json={"reason": "translation_issue"},
        headers=_auth_headers(client, test_user),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "needs_fix"


def test_snooze_and_unsnooze(client, test_user, clean_db):
    source = _source(clean_db)
    cluster = _cluster(clean_db, source)
    draft = _draft(clean_db, cluster)

    snoozed = client.post(
        f"/drafts/{draft.id}/snooze",
        json={"note": "waiting on legal"},
        headers=_auth_headers(client, test_user),
    )
    assert snoozed.status_code == 200
    assert snoozed.json()["status"] == "snoozed"
    assert snoozed.json()["handoff_note"] == "waiting on legal"

    unsnoozed = client.post(
        f"/drafts/{draft.id}/unsnooze", headers=_auth_headers(client, test_user)
    )
    assert unsnoozed.status_code == 200
    assert unsnoozed.json()["status"] == "ready_for_review"
