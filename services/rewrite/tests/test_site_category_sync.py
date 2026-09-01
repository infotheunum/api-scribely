from common.site_category_sync import upsert_theunum_categories
from common.theunum_categories_client import TheunumCategoryRecord
from db.enums import TagCategoryKind
from db.models import TagCategoryCache


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
