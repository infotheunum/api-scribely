"""Orchestrate rewrite filters 1–6 into one review_report."""

from __future__ import annotations

from typing import Any

from rewrite_app.rewrite.banned_phrases import find_banned_phrases, get_banned_phrases
from rewrite_app.rewrite.fact_diff import compare_facts
from rewrite_app.rewrite.quality_gate import review_rewrite
from rewrite_app.rewrite.quote_check import check_quotes
from rewrite_app.rewrite.review_report import (
    FILTER_KEYS,
    build_summary,
    critical_issue_messages,
    empty_filters,
    fact_checks_from_filters,
)
from rewrite_app.settings import RewriteSettings
from sqlalchemy.orm import Session


def run_filters_1_5(
    *,
    source_text: str,
    rewrite_text: str,
    facts_text: str = "",
    banned_phrases: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Deterministic filters: missing / invented / distorted / quotes / banned."""
    filters = empty_filters()
    fact_parts = compare_facts(
        source_text=source_text,
        rewrite_text=rewrite_text,
        facts_text=facts_text,
    )
    fact_parts.pop("_coverage_base", None)
    filters.update(fact_parts)
    filters["quotes"] = check_quotes(source_text=source_text, rewrite_text=rewrite_text)
    filters["banned"] = find_banned_phrases(rewrite_text, phrases=banned_phrases)
    return filters


def run_rewrite_review(
    db: Session,
    settings: RewriteSettings,
    *,
    sources_text: str,
    facts_text: str,
    required_facts_text: str,
    rewritten_text: str,
    rewrite_plain_text: str,
    translate_sources: bool,
    run_semantic: bool = True,
) -> tuple[bool, list[str], dict[str, Any], str | None, str | None, Any]:
    """Run filters 1→5 then optional LLM filter 6; return gate-compatible tuple."""
    banned = get_banned_phrases(db)
    filters = run_filters_1_5(
        source_text=sources_text,
        rewrite_text=rewrite_plain_text,
        facts_text=facts_text,
        banned_phrases=banned,
    )

    usage = None
    key_alias: str | None = None
    model: str | None = None
    language_issues: list[str] = []
    editorial_review_flags: list[str] = []
    blocking_issues: list[str] = []
    translations: list[object] = []
    llm_issues: list[str] = []

    # Skip paid semantic LLM when deterministic filters already reject —
    # regenerate path does not need filter 6 tokens on a doomed draft.
    pre_summary = build_summary(filters)
    run_llm_semantic = run_semantic and pre_summary["critical_count"] == 0

    if run_llm_semantic:
        _approved, llm_issues, semantic_report, key_alias, model, usage = review_rewrite(
            db,
            settings,
            sources_text=sources_text,
            required_facts_text=required_facts_text,
            rewritten_text=rewritten_text,
            translate_sources=translate_sources,
        )
        language_issues = list(semantic_report.get("language_issues") or [])
        editorial_review_flags = list(semantic_report.get("editorial_review_flags") or [])
        blocking_issues = list(semantic_report.get("blocking_issues") or [])
        translations = list(semantic_report.get("translations") or [])
        semantic = (semantic_report.get("filters") or {}).get("semantic")
        if isinstance(semantic, dict):
            filters["semantic"] = semantic
    elif run_semantic and pre_summary["critical_count"] > 0:
        filters["semantic"] = {
            "status": "skipped",
            "severity": "skipped_due_to_critical_filters_1_5",
            "findings": [],
        }

    summary = build_summary(filters)
    fact_checks = fact_checks_from_filters(filters)
    critical_msgs = critical_issue_messages(filters)
    approved = summary["critical_count"] == 0
    issues = [*llm_issues, *critical_msgs]
    seen: set[str] = set()
    deduped: list[str] = []
    for issue in issues:
        if issue in seen:
            continue
        seen.add(issue)
        deduped.append(issue)

    report: dict[str, Any] = {
        "fact_checks": fact_checks,
        "required_fact_checks": [],
        "language_issues": language_issues,
        "editorial_review_flags": editorial_review_flags,
        "blocking_issues": blocking_issues,
        "translations": translations if translate_sources else [],
        "filters": {key: filters[key] for key in FILTER_KEYS},
        "summary": summary,
    }
    return approved, deduped, report, key_alias, model, usage
