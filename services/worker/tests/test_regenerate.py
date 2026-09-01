from __future__ import annotations

from unittest.mock import MagicMock, patch

from db.enums import DraftStatus, SourceTier, SourceType, TopicStatus
from db.models import Draft, DraftExportLog, NewsCluster, RawItem, Source
from common.rewrite_body_limits import BODY_MIN_CHARS
from scribely.rewrite.v1 import rewrite_pb2
from worker_app.dispatch.regenerate import run_regenerate_batch


def _source(db, name="s") -> Source:
    source = Source(
        name=name,
        url=f"https://example.com/{name}",
        type=SourceType.RSS,
        tier=SourceTier.TIER_1,
        language="en",
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _cluster(db, source) -> NewsCluster:
    cluster = NewsCluster(trace_id="t", priority_score=10.0, topic_status=TopicStatus.IN_TOPIC)
    db.add(cluster)
    db.commit()
    db.add(
        RawItem(
            source_id=source.id,
            external_id=f"item-{cluster.id}",
            url=f"https://example.com/{cluster.id}",
            title="Some headline",
            body="Body text.",
            language="en",
            trace_id="t",
            cluster_id=cluster.id,
        )
    )
    db.commit()
    db.refresh(cluster)
    return cluster


def _draft(db, cluster, *, body_len=200) -> Draft:
    draft = Draft(
        cluster_id=cluster.id,
        title_en="Old title EN",
        body_en="x" * body_len,
        title_ru="Old title RU",
        body_ru="y" * body_len,
        attribution_urls=["https://example.com/a"],
        status=DraftStatus.READY_FOR_REVIEW,
        trace_id="trace-old",
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def _fake_enrich_response(cluster_id) -> rewrite_pb2.EnrichClusterResponse:
    return rewrite_pb2.EnrichClusterResponse(
        context=rewrite_pb2.ClusterContext(
            cluster_id=str(cluster_id),
            facts=[rewrite_pb2.ExtractedFact(kind="who", text="Someone")],
        )
    )


def _fake_rewrite_response() -> rewrite_pb2.RewriteClusterResponse:
    return rewrite_pb2.RewriteClusterResponse(
        draft=rewrite_pb2.DraftContent(
            title_en="New title EN",
            body_en="a" * BODY_MIN_CHARS,
            title_ru="New title RU",
            body_ru="b" * BODY_MIN_CHARS,
            attribution_urls=["https://example.com/a"],
            suggested_category_slug="cryptocurrency",
            tags=[rewrite_pb2.TagCandidate(slug="etf", name="ETF")],
            seo_en=rewrite_pb2.SeoPack(seo_title="seo en", keywords=["k"]),
            seo_ru=rewrite_pb2.SeoPack(seo_title="seo ru", keywords=["k"]),
            image_brief=rewrite_pb2.ImageBrief(image_brief="brief", image_alt="alt"),
        ),
        prompt_version_id="",
        rewrite_usage=rewrite_pb2.LlmUsage(key_alias="key_1", model="m"),
        translate_usage=rewrite_pb2.LlmUsage(key_alias="key_1", model="m"),
    )


def test_regenerate_updates_draft_and_clears_export_log(clean_db):
    cluster = _cluster(clean_db, _source(clean_db))
    draft = _draft(clean_db, cluster, body_len=200)
    clean_db.add(
        DraftExportLog(draft_id=draft.id, theunum_reference_id="ref-1", trace_id="export-trace")
    )
    clean_db.commit()

    stub = MagicMock()
    stub.EnrichCluster.side_effect = lambda req, **kw: _fake_enrich_response(cluster.id)
    stub.RewriteCluster.side_effect = lambda req, **kw: _fake_rewrite_response()

    with (
        patch("worker_app.dispatch.regenerate.rewrite_stub", return_value=stub),
        patch("worker_app.dispatch.regenerate.build_rewrite_channel"),
    ):
        result = run_regenerate_batch(clean_db, all_queue=True, limit=10)

    assert result["regenerated"] == 1
    assert result["failed"] == 0
    clean_db.refresh(draft)
    assert draft.title_en == "New title EN"
    assert len(draft.body_en) == BODY_MIN_CHARS
    assert draft.version == 2
    assert clean_db.get(DraftExportLog, draft.id) is None


def test_regenerate_short_only_skips_long_bodies(clean_db):
    cluster = _cluster(clean_db, _source(clean_db))
    _draft(clean_db, cluster, body_len=BODY_MIN_CHARS)

    stub = MagicMock()
    with (
        patch("worker_app.dispatch.regenerate.rewrite_stub", return_value=stub),
        patch("worker_app.dispatch.regenerate.build_rewrite_channel"),
    ):
        result = run_regenerate_batch(clean_db, all_queue=False, limit=10)

    assert result["selected"] == 0
    assert result["regenerated"] == 0
    assert result["failed"] == 0
    assert result["errors"] == []
    assert result["successes"] == []
    stub.EnrichCluster.assert_not_called()
