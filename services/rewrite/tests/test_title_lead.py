"""Unit tests for title≠lead filter (no DB)."""

from rewrite_app.rewrite.title_lead import check_title_lead


def test_title_exact_duplicate_of_lead_is_warning():
    result = check_title_lead(
        title="Oura отложила IPO на Nasdaq",
        body="Oura отложила IPO на Nasdaq. Далее идут детали без цифр.",
        locale="ru",
    )
    assert result["findings"]
    assert result["status"] == "warning"
    assert any("совпадает" in f["message"] for f in result["findings"])


def test_title_with_digit_lead_is_ok():
    result = check_title_lead(
        title="Oura отложила IPO на Nasdaq",
        body=(
            "Производитель умных колец отказался от размещения при оценке почти "
            "$15 млрд из-за роста доходности облигаций."
        ),
        locale="ru",
    )
    assert result["findings"] == []
    assert result["status"] == "ok"


def test_title_fully_covered_by_lead_tokens_warns():
    result = check_title_lead(
        title="Nike превзошла прогноз по прибыли",
        body="Nike превзошла прогноз по прибыли но продажи падают без цифр в лиде.",
        locale="ru",
    )
    assert result["findings"]
