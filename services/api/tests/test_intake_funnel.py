from __future__ import annotations

from datetime import UTC, datetime, timedelta

from common.intake_funnel import build_intake_funnel
from db.app_settings import set_setting
from db.enums import DraftStatus, SourceTier, SourceType, TopicStatus
from db.models import Draft, NewsCluster, RawItem, Source


def _source(db, name: str = "Feed A") -> Source:
    source = Source(
        name=name,
        url=f"https://example.com/{name}",
        type=SourceType.RSS,
        tier=SourceTier.TIER_1,
        language="en",
        is_active=True,
        last_polled_at=datetime.now(UTC),
    )
    db.add(source)
    db.commit()
    return source


def _item(db, source: Source, title: str, *, cluster: NewsCluster | None = None, **kw) -> RawItem:
    now = datetime.now(UTC)
    item = RawItem(
        source_id=source.id,
        external_id=title,
        url=f"https://example.com/{title}",
        title=title,
        language="en",
        published_at=kw.pop("published_at", now),
        fetched_at=kw.pop("fetched_at", now),
        cluster_id=cluster.id if cluster else None,
        trace_id="t",
        **kw,
    )
    db.add(item)
    db.commit()
    return item


def test_intake_funnel_classifies_drafted_vs_eligible(clean_db):
    set_setting(clean_db, "ingestion.max_item_age_hours", 20)
    clean_db.commit()
    source = _source(clean_db)
    drafted = NewsCluster(trace_id="d", topic_status=TopicStatus.IN_TOPIC)
    open_c = NewsCluster(trace_id="o", topic_status=TopicStatus.IN_TOPIC)
    oot = NewsCluster(trace_id="x", topic_status=TopicStatus.OUT_OF_TOPIC)
    clean_db.add_all([drafted, open_c, oot])
    clean_db.commit()
    clean_db.add(
        Draft(
            cluster_id=drafted.id,
            status=DraftStatus.REJECTED,
            title_en="old",
            body_en="b",
            title_ru="с",
            body_ru="с",
            trace_id="draft",
        )
    )
    clean_db.commit()

    _item(clean_db, source, "same-as-rejected", cluster=drafted)
    _item(clean_db, source, "brand-new-eligible", cluster=open_c)
    _item(clean_db, source, "sports-noise", cluster=oot)
    _item(clean_db, source, "still-waiting")  # unclustered

    stats = build_intake_funnel(clean_db, hours=4, sample_limit=10)
    assert stats["totals"]["raw_items_fetched"] == 4
    assert stats["drop_buckets"]["on_drafted_cluster"]["count"] == 1
    assert stats["drop_buckets"]["in_topic_fresh_undrafted"]["count"] == 1
    assert stats["drop_buckets"]["out_of_topic"]["count"] == 1
    assert stats["drop_buckets"]["not_clustered"]["count"] == 1
    assert stats["on_drafted_by_status"]["rejected"] == 1
    titles = {
        row["title"] for row in stats["drop_buckets"]["on_drafted_cluster"]["sample_titles"]
    }
    assert "same-as-rejected" in titles
    assert stats["totals"]["rewrite_eligible_items"] == 1
    assert "свежих undrafted" in stats["verdict"]


def test_intake_funnel_marks_stale_in_topic(clean_db):
    set_setting(clean_db, "ingestion.max_item_age_hours", 20)
    clean_db.commit()
    source = _source(clean_db)
    cluster = NewsCluster(trace_id="stale", topic_status=TopicStatus.IN_TOPIC)
    clean_db.add(cluster)
    clean_db.commit()
    old = datetime.now(UTC) - timedelta(hours=30)
    _item(
        clean_db,
        source,
        "old-pub-but-fetched-now",
        cluster=cluster,
        published_at=old,
        fetched_at=datetime.now(UTC),
    )

    stats = build_intake_funnel(clean_db, hours=4)
    assert stats["drop_buckets"]["in_topic_stale"]["count"] == 1
    assert stats["drop_buckets"]["in_topic_fresh_undrafted"]["count"] == 0


def test_admin_intake_funnel_endpoint(client, admin_user, clean_db):
    source = _source(clean_db)
    _item(clean_db, source, "hello-world")
    resp = client.post(
        "/auth/login",
        data={"username": admin_user.username, "password": "correct-horse-battery-staple"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    out = client.get("/admin/pipeline/intake-funnel?hours=4", headers=headers)
    assert out.status_code == 200
    body = out.json()
    assert body["totals"]["raw_items_fetched"] >= 1
    assert "drop_buckets" in body
    assert "verdict" in body
