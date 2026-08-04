from __future__ import annotations

from api_app.tagsync.client import resolve_tags_and_category
from db.enums import DraftStatus, SourceTier, SourceType, TagCategoryKind
from db.models import Draft, NewsCluster, RawItem, Source, TagCategoryCache


def _draft(db, **overrides) -> Draft:
    source = Source(
        name="s",
        url="https://example.com/feed",
        type=SourceType.RSS,
        tier=SourceTier.TIER_1,
        language="en",
    )
    db.add(source)
    db.commit()
    cluster = NewsCluster(trace_id="t")
    db.add(cluster)
    db.commit()
    db.add(
        RawItem(
            source_id=source.id,
            external_id="i",
            url="https://example.com/1",
            title="t",
            language="en",
            trace_id="t",
            cluster_id=cluster.id,
        )
    )
    defaults = dict(
        cluster_id=cluster.id,
        title_en="x",
        body_en="x" * 150,
        title_ru="y",
        body_ru="y" * 150,
        trace_id="t",
        status=DraftStatus.READY_FOR_REVIEW,
    )
    defaults.update(overrides)
    draft = Draft(**defaults)
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def test_resolves_new_pending_tags_to_mock_ids(clean_db):
    draft = _draft(clean_db, pending_tags=[{"slug": "bitcoin", "name": "Bitcoin"}])

    category_id, tag_ids = resolve_tags_and_category(clean_db, draft)

    assert category_id is None
    assert tag_ids == ["mock-tag-bitcoin"]
    cached = clean_db.get(TagCategoryCache, "mock-tag-bitcoin")
    assert cached is not None
    assert cached.kind == TagCategoryKind.TAG
    assert cached.slug == "bitcoin"


def test_reuses_existing_cache_entry_by_slug_instead_of_creating_duplicate(clean_db):
    clean_db.add(
        TagCategoryCache(
            id="real-tag-42", kind=TagCategoryKind.TAG, slug="bitcoin", name_en="Bitcoin"
        )
    )
    clean_db.commit()
    draft = _draft(clean_db, pending_tags=[{"slug": "bitcoin", "name": "Bitcoin"}])

    _, tag_ids = resolve_tags_and_category(clean_db, draft)

    assert tag_ids == ["real-tag-42"]
    assert clean_db.query(TagCategoryCache).filter_by(slug="bitcoin").count() == 1


def test_resolves_pending_category_slug(clean_db):
    draft = _draft(clean_db, pending_category_slug="markets")

    category_id, _ = resolve_tags_and_category(clean_db, draft)

    assert category_id == "mock-category-markets"


def test_already_resolved_ids_pass_through_unchanged(clean_db):
    draft = _draft(clean_db, category_id="existing-cat", tag_ids=["existing-tag"], pending_tags=[])

    category_id, tag_ids = resolve_tags_and_category(clean_db, draft)

    assert category_id == "existing-cat"
    assert tag_ids == ["existing-tag"]


def test_duplicate_pending_tag_does_not_repeat_in_tag_ids(clean_db):
    draft = _draft(
        clean_db,
        tag_ids=["mock-tag-bitcoin"],
        pending_tags=[{"slug": "bitcoin", "name": "Bitcoin"}, {"slug": "etf", "name": "ETF"}],
    )

    _, tag_ids = resolve_tags_and_category(clean_db, draft)

    assert tag_ids == ["mock-tag-bitcoin", "mock-tag-etf"]
