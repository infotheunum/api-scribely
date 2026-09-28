"""Shared shapes for the six-filter rewrite review report."""

from __future__ import annotations

from typing import Any, Literal

Severity = Literal["critical", "warning"]
FilterStatus = Literal["ok", "warning", "critical"]
Verdict = Literal["publishable", "needs_attention", "blocked"]

FILTER_KEYS = (
    "missing",
    "invented",
    "distorted",
    "quotes",
    "banned",
    "semantic",
)


def finding(
    *,
    severity: Severity,
    message: str,
    source_span: str | None = None,
    rewrite_span: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "severity": severity,
        "message": message,
        "source_span": source_span or "",
        "rewrite_span": rewrite_span or "",
    }
    if category:
        item["category"] = category
    return item


def filter_result(findings: list[dict[str, Any]]) -> dict[str, Any]:
    if any(f.get("severity") == "critical" for f in findings):
        status: FilterStatus = "critical"
    elif findings:
        status = "warning"
    else:
        status = "ok"
    return {"status": status, "findings": findings}


def empty_filters() -> dict[str, Any]:
    return {key: filter_result([]) for key in FILTER_KEYS}


def build_summary(filters: dict[str, Any]) -> dict[str, Any]:
    """Aggregate filter findings into the short editor card."""
    critical_count = 0
    warning_count = 0
    invented_count = len(filters.get("invented", {}).get("findings") or [])
    quotes_issues = len(filters.get("quotes", {}).get("findings") or [])
    banned_counts: dict[str, int] = {}
    for item in filters.get("banned", {}).get("findings") or []:
        category = str(item.get("category") or "other")
        banned_counts[category] = banned_counts.get(category, 0) + 1

    missing = filters.get("missing", {}).get("findings") or []
    distorted = filters.get("distorted", {}).get("findings") or []
    source_hits = int(filters.get("missing", {}).get("source_entity_count") or 0)
    lost = len(missing) + len(distorted)
    if source_hits > 0:
        facts_coverage_pct = max(0, round(100 * (source_hits - lost) / source_hits))
    else:
        facts_coverage_pct = 100

    for key in FILTER_KEYS:
        for item in filters.get(key, {}).get("findings") or []:
            if item.get("severity") == "critical":
                critical_count += 1
            else:
                warning_count += 1

    if critical_count > 0:
        verdict: Verdict = "blocked"
    elif warning_count > 0:
        verdict = "needs_attention"
    else:
        verdict = "publishable"

    return {
        "facts_coverage_pct": facts_coverage_pct,
        "invented_count": invented_count,
        "quotes_issues": quotes_issues,
        "banned_counts": banned_counts,
        "verdict": verdict,
        "critical_count": critical_count,
        "warning_count": warning_count,
    }


def fact_checks_from_filters(filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Map filters 1–3 into legacy fact_checks rows for older UI/export consumers."""
    rows: list[dict[str, Any]] = []
    mapping = (
        ("missing", "упущен"),
        ("invented", "добавлено"),
        ("distorted", "искажён"),
    )
    for key, status in mapping:
        for item in filters.get(key, {}).get("findings") or []:
            severity = item.get("severity") or "secondary"
            rows.append(
                {
                    "fact": item.get("source_span") or item.get("message") or "",
                    "status": status,
                    "severity": "critical" if severity == "critical" else "secondary",
                    "rewrite_evidence": item.get("rewrite_span") or "",
                }
            )
    return rows


def critical_issue_messages(filters: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    for key in FILTER_KEYS:
        for item in filters.get(key, {}).get("findings") or []:
            if item.get("severity") == "critical":
                messages.append(str(item.get("message") or key))
    return messages
