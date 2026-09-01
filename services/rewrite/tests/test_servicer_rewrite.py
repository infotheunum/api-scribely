from __future__ import annotations

import json

import grpc
import pytest
from rewrite_app.prompt.style_guide import BODY_MIN_CHARS
from rewrite_app.server import build_server
from rewrite_app.settings import RewriteSettings
from scribely.rewrite.v1 import rewrite_pb2, rewrite_pb2_grpc

TOKEN = "test-token"

VALID_RESULT = {
    "title_en": "Bitcoin Surges Past $120,000 as ETF Inflows Accelerate",
    "body_en": "x" * BODY_MIN_CHARS,
    "title_ru": "Биткоин превысил $120,000 на фоне роста притоков в ETF",
    "body_ru": "y" * BODY_MIN_CHARS,
    "title_en_variants": [],
    "title_ru_variants": [],
    "sponsor_flag": False,
    "press_release_flag": False,
    "disclaimer_flag": True,
    "suggested_category_slug": "cryptocurrency",
    "tags": [{"slug": "etf", "name": "ETF"}],
    "seo_en": {
        "seo_title": "t",
        "seo_description": "d",
        "slug": "s",
        "og_title": "o",
        "og_description": "od",
        "focus_keyphrase": "bitcoin etf",
        "keywords": ["bitcoin"],
    },
    "seo_ru": {
        "seo_title": "t",
        "seo_description": "d",
        "slug": "s",
        "og_title": "o",
        "og_description": "od",
        "focus_keyphrase": "биткоин etf",
        "keywords": ["биткоин"],
    },
    "image_brief": {
        "image_brief": "b",
        "image_mood": "neutral",
        "image_subjects": ["bitcoin"],
        "image_style": "photo",
        "image_do_not": [],
        "image_alt": "a",
        "image_caption": "c",
        "image_source_suggestion": "s",
    },
}


@pytest.fixture
def server_address():
    settings = RewriteSettings(grpc_port=0, internal_service_token=TOKEN)
    server = build_server(settings)
    port = server.add_insecure_port("0.0.0.0:0")
    server.start()
    try:
        yield f"localhost:{port}"
    finally:
        server.stop(grace=None)


def _md():
    return (("x-service-token", TOKEN),)


def test_enrich_cluster_over_grpc(clean_db, server_address, monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.servicer.enrich_cluster",
        lambda *a, **kw: (
            _fake_enrich_result(),
            "key_1",
            "openai/gpt-oss-20b:free",
        ),
    )
    with grpc.insecure_channel(server_address) as channel:
        stub = rewrite_pb2_grpc.RewriteServiceStub(channel)
        request = rewrite_pb2.EnrichClusterRequest(
            cluster_id="c1",
            trace_id="t1",
            sources=[
                rewrite_pb2.SourceRef(
                    raw_item_id="r1",
                    title="Title",
                    url="https://example.com",
                    language="en",
                    excerpt_or_full_text="body text",
                    source_name="Test Wire",
                )
            ],
        )
        response = stub.EnrichCluster(request, metadata=_md())

    assert response.context.cluster_id == "c1"
    assert response.context.regulated is True
    assert len(response.context.facts) == 1


def test_rewrite_cluster_over_grpc(clean_db, server_address, monkeypatch):
    monkeypatch.setattr(
        "rewrite_app.servicer.rewrite_cluster",
        lambda *a, **kw: (
            _fake_rewrite_result(),
            "key_1",
            "openai/gpt-oss-20b:free",
        ),
    )
    with grpc.insecure_channel(server_address) as channel:
        stub = rewrite_pb2_grpc.RewriteServiceStub(channel)
        request = rewrite_pb2.RewriteClusterRequest(
            context=rewrite_pb2.ClusterContext(
                cluster_id="c1",
                sources=[
                    rewrite_pb2.SourceRef(
                        raw_item_id="r1",
                        title="Title",
                        url="https://example.com/a",
                        language="en",
                        excerpt_or_full_text="body",
                        source_name="Test Wire",
                    )
                ],
                fact_conflict=False,
            ),
            trace_id="t1",
        )
        response = stub.RewriteCluster(request, metadata=_md())

    assert response.draft.title_en == VALID_RESULT["title_en"]
    assert response.draft.attribution_urls == ["https://example.com/a"]
    assert response.prompt_version_id  # a PromptVersion got bootstrapped
    assert response.rewrite_usage.key_alias == "key_1"


def _fake_enrich_result():
    from rewrite_app.rewrite.schemas import EnrichResultSchema

    return EnrichResultSchema.model_validate(
        {
            "facts": [{"kind": "who", "text": "SEC"}],
            "press_release": False,
            "regulated": True,
            "market_sensitive": False,
            "fact_conflict": False,
            "fact_conflict_note": "",
        }
    )


def _fake_rewrite_result():
    from rewrite_app.rewrite.schemas import RewriteResultSchema

    return RewriteResultSchema.model_validate(json.loads(json.dumps(VALID_RESULT)))
