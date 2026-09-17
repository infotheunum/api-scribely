from common.seo_review import review_draft_seo, seo_blocking_issues


def test_seo_review_blocks_typo_and_unsupported_number():
    report = review_draft_seo(
        title_ru="Японская FSA назвала блокчейн приоритетом на 2026 год",
        body_ru="Японская FSA назвала адаптацию блокчейна приоритетом на 2026 год.",
        seo_title_ru="Япония приоритизерует блокчейн в 2026 году",
        seo_description_ru="Тем не менее, FSA не раскрыла дополнительные детали.",
        focus_keyphrase_ru="блокчейн",
        title_en="Japan FSA sets blockchain priority for 2026",
        body_en="Japan FSA set blockchain adaptation as a priority for 2026.",
        seo_title_en="Japan FSA sets blockchain priority for 2026",
        seo_description_en="Japan FSA set blockchain adaptation as a priority for 2026.",
        focus_keyphrase_en="blockchain",
    )

    evidence = " ".join(issue["evidence"] for issue in seo_blocking_issues(report))
    assert "приоритизерует" in evidence
    assert "Тем не менее" in evidence


def test_seo_review_warns_for_length_without_blocking():
    report = review_draft_seo(
        title_ru="Биткоин вырос",
        body_ru="Биткоин вырос после публикации данных.",
        seo_title_ru="Биткоин вырос",
        seo_description_ru="Цена выросла.",
        focus_keyphrase_ru="биткоин",
        title_en="Bitcoin rose",
        body_en="Bitcoin rose after the data release.",
        seo_title_en="Bitcoin rose",
        seo_description_en="Price rose.",
        focus_keyphrase_en="bitcoin",
    )

    assert not seo_blocking_issues(report)
    assert any(issue["rule"] == "length" for issue in report["ru"]["issues"])
