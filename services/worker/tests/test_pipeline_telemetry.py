from __future__ import annotations

from unittest.mock import MagicMock, patch

import grpc
from common.pipeline_telemetry import KEY_LAST_ERROR_CODE, KEY_LAST_DISPATCH_FAILED
from db.app_settings import get_setting
from db.enums import SourceTier, SourceType, TopicStatus
from db.models import NewsCluster, Source
from worker_app.dispatch.pipeline import run_dispatch_cycle


def _patched_stub(enrich_side_effect=None, rewrite_side_effect=None):
    stub = MagicMock()
    stub.EnrichCluster.side_effect = enrich_side_effect
    stub.RewriteCluster.side_effect = rewrite_side_effect
    return patch("worker_app.dispatch.pipeline.rewrite_stub", return_value=stub), stub


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
    db.refresh(cluster)
    return cluster


def test_dispatch_records_openrouter_error_in_app_settings(clean_db):
    _cluster(clean_db, _source(clean_db))
    error = grpc.RpcError()
    error.code = lambda: grpc.StatusCode.UNAVAILABLE
    error.details = lambda: (
        "[reason=openrouter_payment_required] all OpenRouter keys exhausted: insufficient credits"
    )

    patcher, _stub = _patched_stub(enrich_side_effect=error)

    with patcher, patch("worker_app.dispatch.pipeline.build_rewrite_channel"):
        run_dispatch_cycle(clean_db)

    assert get_setting(clean_db, KEY_LAST_DISPATCH_FAILED, 0) == 1
    assert get_setting(clean_db, KEY_LAST_ERROR_CODE, "") == "openrouter_payment_required"


def test_dispatch_classifies_unstructured_grpc_error(clean_db):
    """Backward compat when rewrite details omit [reason=] prefix."""
    _cluster(clean_db, _source(clean_db))
    error = grpc.RpcError()
    error.code = lambda: grpc.StatusCode.UNAVAILABLE
    error.details = lambda: "all OpenRouter keys exhausted: HTTP 429: rate limit"

    patcher, _stub = _patched_stub(enrich_side_effect=error)

    with patcher, patch("worker_app.dispatch.pipeline.build_rewrite_channel"):
        run_dispatch_cycle(clean_db)

    assert get_setting(clean_db, KEY_LAST_ERROR_CODE, "") == "openrouter_rate_limited"
