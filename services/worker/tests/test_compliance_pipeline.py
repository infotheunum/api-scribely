from __future__ import annotations

from db.enums import DraftStatus, SourceTier, SourceType
from db.models import Draft, NewsCluster, RawItem, Source
from worker_app.compliance.pipeline import run_compliance_cycle


def _source(db, *, tier=SourceTier.TIER_1) -> Source:
    source = Source(
        name="s", url=f"https://example.com/{tier}", type=SourceType.RSS, tier=tier, language="en"
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _cluster_with_item(
    db, source, *, body="Some real crypto news body about a real event."
) -> NewsCluster:
    cluster = NewsCluster(trace_id="t")
    db.add(cluster)
    db.commit()
    db.add(
        RawItem(
            source_id=source.id,
            external_id=f"item-{cluster.id}",
            url=f"https://example.com/{cluster.id}",
            title="Source headline",
            body=body,
            language="en",
            trace_id="t",
            cluster_id=cluster.id,
        )
    )
    db.commit()
    db.refresh(cluster)
    return cluster


def _draft(db, cluster, **overrides) -> Draft:
    defaults = dict(
        cluster_id=cluster.id,
        title_en="A clean headline about crypto",
        body_en="x" * 150,
        title_ru="y" * 20,
        body_ru="y" * 150,
        attribution_urls=["https://example.com/a"],
        trace_id="t",
        status=DraftStatus.DRAFTING,
    )
    defaults.update(overrides)
    draft = Draft(**defaults)
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def test_clean_draft_reaches_ready_for_review(clean_db):
    source = _source(clean_db)
    cluster = _cluster_with_item(clean_db, source)
    draft = _draft(clean_db, cluster)

    stats = run_compliance_cycle(clean_db)

    clean_db.refresh(draft)
    assert stats["ready"] == 1
    assert draft.status == DraftStatus.READY_FOR_REVIEW
    assert draft.sensitive_hold is False


def test_missing_attribution_needs_fix(clean_db):
    source = _source(clean_db)
    cluster = _cluster_with_item(clean_db, source)
    draft = _draft(clean_db, cluster, attribution_urls=[])

    run_compliance_cycle(clean_db)

    clean_db.refresh(draft)
    assert draft.status == DraftStatus.NEEDS_FIX
    assert any("attribution" in note for note in draft.compliance_notes)


def test_forbidden_content_blocks_promotion(clean_db):
    source = _source(clean_db)
    cluster = _cluster_with_item(clean_db, source)
    draft = _draft(
        clean_db, cluster, body_en="Act now: buy now for guaranteed profits!" + "x" * 100
    )

    stats = run_compliance_cycle(clean_db)

    clean_db.refresh(draft)
    assert stats["blocked"] == 1
    assert draft.status == DraftStatus.DRAFTING
    assert any("forbidden content" in note for note in draft.compliance_notes)


def test_press_release_by_tier_forces_flag(clean_db):
    source = _source(clean_db, tier=SourceTier.TIER_6)
    cluster = _cluster_with_item(clean_db, source)
    draft = _draft(clean_db, cluster, press_release_flag=False)

    run_compliance_cycle(clean_db)

    clean_db.refresh(draft)
    assert draft.press_release_flag is True


def test_fact_conflict_needs_fix(clean_db):
    source = _source(clean_db)
    cluster = _cluster_with_item(clean_db, source)
    draft = _draft(clean_db, cluster, fact_conflict=True)

    run_compliance_cycle(clean_db)

    clean_db.refresh(draft)
    assert draft.status == DraftStatus.NEEDS_FIX


def test_sensitive_topic_sets_hold_without_blocking(clean_db):
    source = _source(clean_db)
    cluster = _cluster_with_item(clean_db, source)
    draft = _draft(
        clean_db,
        cluster,
        title_en="Exchange hacked, funds stolen in major breach",
        body_en="Attackers hacked the exchange and stole user funds. " * 3 + "x" * 50,
    )

    run_compliance_cycle(clean_db)

    clean_db.refresh(draft)
    assert draft.sensitive_hold is True
    assert draft.status == DraftStatus.READY_FOR_REVIEW
    assert any("sensitive_hold" in note for note in draft.compliance_notes)


def test_similarity_gate_blocks_near_verbatim_copy(clean_db):
    source_body = (
        "Coinbase reported second-quarter earnings below Wall Street expectations "
        "as trading volumes slowed across the exchange, marking a sharp reversal "
        "from the prior year's strong performance in digital asset markets."
    )
    source = _source(clean_db)
    cluster = _cluster_with_item(clean_db, source, body=source_body)
    # Near-verbatim copy of the source body — should trip the gate.
    draft = _draft(clean_db, cluster, title_en="Coinbase Q2 earnings", body_en=source_body)

    run_compliance_cycle(clean_db)

    clean_db.refresh(draft)
    assert draft.status == DraftStatus.NEEDS_FIX
    assert draft.similarity_score is not None
    assert draft.similarity_score > 0.9
    assert any("similarity" in note for note in draft.compliance_notes)
