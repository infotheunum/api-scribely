"""Publish disclaimer texts (AppSetting-backed)."""

from __future__ import annotations

from typing import Any, Literal

from db.app_settings import get_setting
from sqlalchemy.orm import Session

DisclaimerVariant = Literal["crypto", "tech", "strict"]

DEFAULT_DISCLAIMER_RU = (
    "Материал носит информационный характер и не является инвестиционной "
    "рекомендацией. Редакция не несёт ответственности за возможные убытки, "
    "связанные с использованием упомянутых активов. Проводите собственное "
    "исследование перед принятием решений."
)
DEFAULT_DISCLAIMER_EN = (
    "This material is for informational purposes only and is not investment "
    "advice. The editors are not responsible for any losses related to the "
    "assets mentioned. Do your own research before making decisions."
)
DEFAULT_DISCLAIMER_TECH_RU = (
    "Материал носит информационный характер. Упоминание компаний и продуктов "
    "не является рекламой или рекомендацией."
)
DEFAULT_DISCLAIMER_TECH_EN = (
    "This material is for informational purposes only. Mentions of companies "
    "or products are not advertising or recommendations."
)
DEFAULT_DISCLAIMER_STRICT_RU = (
    "Материал носит информационный характер и не является финансовой, "
    "юридической или медицинской рекомендацией. Перед принятием решений "
    "проконсультируйтесь со специалистом и проведите собственное исследование."
)
DEFAULT_DISCLAIMER_STRICT_EN = (
    "This material is for informational purposes only and is not financial, "
    "legal, or medical advice. Consult a qualified professional and do your "
    "own research before making decisions."
)

KEY_RU = "publish.disclaimer.ru"
KEY_EN = "publish.disclaimer.en"
KEY_TECH_RU = "publish.disclaimer.tech.ru"
KEY_TECH_EN = "publish.disclaimer.tech.en"
KEY_STRICT_RU = "publish.disclaimer.strict.ru"
KEY_STRICT_EN = "publish.disclaimer.strict.en"

_CRYPTO_SLUGS = frozenset({"crypto", "cryptocurrency", "defi", "bitcoin", "markets"})
_TECH_SLUGS = frozenset({"ai", "tech", "technology", "software"})
_STRICT_SLUGS = frozenset({"health", "legal", "finance", "law", "medicine"})


def _as_str(value: Any, default: str) -> str:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        text = value.strip()
        return text or default
    return str(value).strip() or default


def resolve_disclaimer_variant(category_slug: str | None) -> DisclaimerVariant:
    slug = (category_slug or "").strip().lower()
    if slug in _STRICT_SLUGS:
        return "strict"
    if slug in _TECH_SLUGS:
        return "tech"
    if slug in _CRYPTO_SLUGS:
        return "crypto"
    return "crypto"


def get_disclaimer_text(
    db: Session | None,
    *,
    locale: str,
    variant: DisclaimerVariant = "crypto",
) -> str:
    locale = (locale or "ru").lower()
    if variant == "tech":
        key = KEY_TECH_RU if locale.startswith("ru") else KEY_TECH_EN
        default = (
            DEFAULT_DISCLAIMER_TECH_RU
            if locale.startswith("ru")
            else DEFAULT_DISCLAIMER_TECH_EN
        )
    elif variant == "strict":
        key = KEY_STRICT_RU if locale.startswith("ru") else KEY_STRICT_EN
        default = (
            DEFAULT_DISCLAIMER_STRICT_RU
            if locale.startswith("ru")
            else DEFAULT_DISCLAIMER_STRICT_EN
        )
    else:
        key = KEY_RU if locale.startswith("ru") else KEY_EN
        default = DEFAULT_DISCLAIMER_RU if locale.startswith("ru") else DEFAULT_DISCLAIMER_EN
    if db is None:
        return default
    return _as_str(get_setting(db, key, default), default)


def append_disclaimer(body: str, disclaimer: str) -> str:
    """Append disclaimer once; no-op if empty or already present."""
    body = (body or "").rstrip()
    disclaimer = (disclaimer or "").strip()
    if not body or not disclaimer:
        return body
    if disclaimer in body:
        return body
    return f"{body}\n\n{disclaimer}"


def apply_disclaimer_to_bodies(
    db: Session | None,
    *,
    body_en: str,
    body_ru: str,
    enabled: bool,
    category_slug: str | None = None,
) -> tuple[str, str]:
    if not enabled:
        return body_en or "", body_ru or ""
    variant = resolve_disclaimer_variant(category_slug)
    en = append_disclaimer(body_en or "", get_disclaimer_text(db, locale="en", variant=variant))
    ru = append_disclaimer(body_ru or "", get_disclaimer_text(db, locale="ru", variant=variant))
    return en, ru
