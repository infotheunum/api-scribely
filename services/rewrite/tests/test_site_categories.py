from common.site_categories import bootstrap_site_categories_if_empty, is_valid_site_category_slug, resolve_site_category_slug


def test_llm_garbage_slug_maps_to_crypto(clean_db):
    bootstrap_site_categories_if_empty(clean_db)
    assert (
        resolve_site_category_slug(
            "ethereum-treasury",
            db=clean_db,
            editorial_topic="Криптовалюты и цифровые активы",
        )
        == "cryptocurrency"
    )


def test_unknown_falls_back_to_world(clean_db):
    bootstrap_site_categories_if_empty(clean_db)
    assert (
        resolve_site_category_slug("kalshi-lifetime-ban", db=clean_db, hint_text="Congress candidate")
        == "world"
    )


def test_editorial_topic_macro_to_economy(clean_db):
    bootstrap_site_categories_if_empty(clean_db)
    assert (
        resolve_site_category_slug(
            "markets",
            db=clean_db,
            editorial_topic="Финансовые и экономические события",
        )
        == "economy"
    )


def test_is_valid_site_category_slug(clean_db):
    bootstrap_site_categories_if_empty(clean_db)
    assert is_valid_site_category_slug(clean_db, "cryptocurrency")
    assert not is_valid_site_category_slug(clean_db, "defi")
    assert not is_valid_site_category_slug(clean_db, None)
