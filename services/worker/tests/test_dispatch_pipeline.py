from __future__ import annotations

from unittest.mock import MagicMock, patch

import grpc
from db.app_settings import set_setting
from db.enums import DraftStatus, SourceTier, SourceType, TopicStatus
from db.models import ClusterContext, Draft, DraftRevision, NewsCluster, RawItem, Source
from scribely.rewrite.v1 import rewrite_pb2
from worker_app.dispatch.pipeline import DISPATCH_BATCH_SIZE, run_dispatch_cycle


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


def _cluster(db, source, *, score=10.0) -> NewsCluster:
    cluster = NewsCluster(trace_id="t", priority_score=score, topic_status=TopicStatus.IN_TOPIC)
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


def _fake_enrich_response(cluster_id) -> rewrite_pb2.EnrichClusterResponse:
    return rewrite_pb2.EnrichClusterResponse(
        context=rewrite_pb2.ClusterContext(
            cluster_id=str(cluster_id),
            facts=[rewrite_pb2.ExtractedFact(kind="who", text="Someone")],
            press_release=False,
            regulated=True,
            market_sensitive=False,
            fact_conflict=False,
        )
    )


def _fake_rewrite_response() -> rewrite_pb2.RewriteClusterResponse:
    return rewrite_pb2.RewriteClusterResponse(
        draft=rewrite_pb2.DraftContent(
            title_en="x" * 20,
            body_en="x" * 200,
            title_ru="y" * 20,
            body_ru="y" * 200,
            attribution_urls=["https://example.com/a"],
            suggested_category_slug="cryptocurrency",
            tags=[rewrite_pb2.TagCandidate(slug="etf", name="ETF")],
            seo_en=rewrite_pb2.SeoPack(seo_title="t", keywords=["k"]),
            seo_ru=rewrite_pb2.SeoPack(seo_title="t", keywords=["k"]),
            image_brief=rewrite_pb2.ImageBrief(image_brief="b", image_alt="a"),
        ),
        prompt_version_id="",
        rewrite_usage=rewrite_pb2.LlmUsage(key_alias="key_1", model="m"),
        translate_usage=rewrite_pb2.LlmUsage(key_alias="key_1", model="m"),
    )


def _patched_stub(enrich_side_effect=None, rewrite_side_effect=None):
    stub = MagicMock()
    stub.EnrichCluster.side_effect = enrich_side_effect
    stub.RewriteCluster.side_effect = rewrite_side_effect
    return patch("worker_app.dispatch.pipeline.rewrite_stub", return_value=stub), stub


def test_dispatch_persists_draft_and_revision(clean_db):
    cluster = _cluster(clean_db, _source(clean_db))
    patcher, stub = _patched_stub(
        enrich_side_effect=lambda req, **kw: _fake_enrich_response(cluster.id),
        rewrite_side_effect=lambda req, **kw: _fake_rewrite_response(),
    )
    with patcher, patch("worker_app.dispatch.pipeline.build_rewrite_channel"):
        stats = run_dispatch_cycle(clean_db)

    assert stats == {"dispatched": 1, "failed": 0}
    draft = clean_db.query(Draft).one()
    assert draft.cluster_id == cluster.id
    # DRAFTING, not READY_FOR_REVIEW — the Policy/Compliance Checker
    # (Фаза 5, worker_app/compliance/pipeline.py) gates it next tick.
    assert draft.status == DraftStatus.DRAFTING
    assert draft.title_en == "x" * 20
    assert draft.pending_tags == [{"slug": "etf", "name": "ETF"}]
    assert draft.rewrite_llm_key_alias == "key_1"
    assert draft.rewrite_llm_model == "m"
    assert draft.translate_llm_key_alias == "key_1"
    assert draft.translate_llm_model == "m"
    revision = clean_db.query(DraftRevision).one()
    assert revision.draft_id == draft.id
    assert revision.kind == "ai_generated"
    ctx = clean_db.get(ClusterContext, cluster.id)
    assert ctx is not None
    assert ctx.regulated is True


def test_dispatch_skips_clusters_that_already_have_a_draft(clean_db):
    source = _source(clean_db)
    already_drafted = _cluster(clean_db, source, score=99)
    fresh = _cluster(clean_db, source, score=1)
    clean_db.add(
        Draft(cluster_id=already_drafted.id, trace_id="t", status=DraftStatus.READY_FOR_REVIEW)
    )
    clean_db.commit()

    seen_cluster_ids = []

    def _enrich(req, **kw):
        seen_cluster_ids.append(req.cluster_id)
        return _fake_enrich_response(fresh.id)

    patcher, stub = _patched_stub(
        enrich_side_effect=_enrich, rewrite_side_effect=lambda req, **kw: _fake_rewrite_response()
    )
    with patcher, patch("worker_app.dispatch.pipeline.build_rewrite_channel"):
        stats = run_dispatch_cycle(clean_db)

    assert stats["dispatched"] == 1
    assert seen_cluster_ids == [str(fresh.id)]


def test_dispatch_leaves_cluster_undrafted_on_rpc_failure(clean_db):
    _cluster(clean_db, _source(clean_db))
    error = grpc.RpcError()
    error.code = lambda: grpc.StatusCode.UNAVAILABLE
    error.details = lambda: "all OpenRouter keys exhausted"
    patcher, stub = _patched_stub(enrich_side_effect=error)
    with patcher, patch("worker_app.dispatch.pipeline.build_rewrite_channel"):
        stats = run_dispatch_cycle(clean_db)

    assert stats == {"dispatched": 0, "failed": 1}
    assert clean_db.query(Draft).count() == 0


def test_dispatch_respects_batch_size_cap(clean_db):
    source = _source(clean_db)
    for i in range(DISPATCH_BATCH_SIZE + 2):
        _cluster(clean_db, source, score=float(i))

    patcher, stub = _patched_stub(
        enrich_side_effect=lambda req, **kw: _fake_enrich_response(req.cluster_id),
        rewrite_side_effect=lambda req, **kw: _fake_rewrite_response(),
    )
    with patcher, patch("worker_app.dispatch.pipeline.build_rewrite_channel"):
        stats = run_dispatch_cycle(clean_db)

    assert stats["dispatched"] == DISPATCH_BATCH_SIZE


def test_dispatch_batch_size_honors_app_setting_override(clean_db):
    source = _source(clean_db)
    for i in range(5):
        _cluster(clean_db, source, score=float(i))
    set_setting(clean_db, "dispatch.batch_size", 2)
    clean_db.commit()

    patcher, stub = _patched_stub(
        enrich_side_effect=lambda req, **kw: _fake_enrich_response(req.cluster_id),
        rewrite_side_effect=lambda req, **kw: _fake_rewrite_response(),
    )
    with patcher, patch("worker_app.dispatch.pipeline.build_rewrite_channel"):
        stats = run_dispatch_cycle(clean_db)

    assert stats["dispatched"] == 2
