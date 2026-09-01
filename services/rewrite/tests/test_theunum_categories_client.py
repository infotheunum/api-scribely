from unittest.mock import MagicMock

from common.theunum_categories_client import fetch_theunum_categories


def test_fetch_merges_en_and_ru_locales(monkeypatch):
    responses = {
        "locale=en": {"items": [{"id": "1", "slug": "cryptocurrency", "name": "Cryptocurrency"}]},
        "locale=ru": {"items": [{"id": "1", "slug": "cryptocurrency", "name": "Криптовалюта"}]},
    }

    def fake_get(url, **kwargs):
        response = MagicMock()
        response.raise_for_status = MagicMock()
        if "locale=en" in url:
            response.json.return_value = responses["locale=en"]
        else:
            response.json.return_value = responses["locale=ru"]
        return response

    monkeypatch.setattr("common.theunum_categories_client.httpx.get", fake_get)

    records = fetch_theunum_categories(
        base_url="https://api.theunum.io",
        path="/api/v1/categories",
    )
    assert len(records) == 1
    assert records[0].slug == "cryptocurrency"
    assert records[0].name_en == "Cryptocurrency"
    assert records[0].name_ru == "Криптовалюта"
