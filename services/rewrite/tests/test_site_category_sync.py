import uuid

from common.site_category_sync import upsert_theunum_categories
from common.theunum_categories_client import TheunumCategoryRecord
from db.enums import DraftStatus, TagCategoryKind
from db.models import Draft, NewsCluster, TagCategoryCache


def test_upsert_creates_and_deactivates_missing(clean_db):
    stats = upsert_theunum_categories(
        clean_db,
        [
            TheunumCategoryRecord(id="cat-1", slug="crypto", name_en="Crypto", name_ru="Криптовалюта"),
            TheunumCategoryRecord(id="cat-2", slug="world", name_en="World", name_ru="Мир"),
        ],
    )
    assert stats["created"] == 2

    stats2 = upsert_theunum_categories(
        clean_db,
        [
            TheunumCategoryRecord(id="cat-1", slug="crypto", name_en="Crypto", name_ru="Криптовалюта"),
            TheunumCategoryRecord(id="cat-3", slug="finance", name_en="Finance", name_ru="Финансы"),
        ],
    )
    assert stats2["created"] == 1
    assert stats2["deactivated"] == 1

    world = clean_db.query(TagCategoryCache).filter_by(slug="world", kind=TagCategoryKind.CATEGORY).one()
    assert world.is_active is False


def test_upsert_merges_slug_rename_by_id_and_deactivates_legacy(clean_db):
    cluster_id = uuid.uuid4()
    clean_db.add(NewsCluster(id=cluster_id, trace_id="cluster-trace"))
    clean_db.add(
        TagCategoryCache(
            id="79a3a5fb-b491-570f-a5d5-5814eafbeb46",
            kind=TagCategoryKind.CATEGORY,
            slug="cryptocurrency",
            name_ru="Криптовалюта",
            is_active=True,
        )
    )
    clean_db.add(
        Draft(
            cluster_id=cluster_id,
            trace_id="trace",
            status=DraftStatus.READY_FOR_REVIEW,
            pending_category_slug="defi",
        )
    )
    clean_db.commit()

    stats = upsert_theunum_categories(
        clean_db,
        [
            TheunumCategoryRecord(
                id="79a3a5fb-b491-570f-a5d5-5814eafbeb46",
                slug="crypto",
                name_en="Crypto",
                name_ru="Криптовалюта",
            ),
        ],
    )
    clean_db.commit()

    row = clean_db.get(
        TagCategoryCache,
        "79a3a5fb-b491-570f-a5d5-5814eafbeb46",
    )
    assert row is not None
    assert row.slug == "crypto"
    assert "cryptocurrency" in row.aliases
    assert row.is_active is True
    assert stats["drafts_changed"] == 1
    assert clean_db.query(Draft).one().pending_category_slug == "crypto"
