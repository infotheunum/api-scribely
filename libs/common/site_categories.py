from __future__ import annotations

import re

from db.app_settings import get_setting
from db.enums import TagCategoryKind
from db.models import TagCategoryCache
from sqlalchemy import select
from sqlalchemy.orm import Session

FALLBACK_SLUG_SETTING = "site_category.fallback_slug"

# Slugs и id совпадают с GET /api/v1/categories?locale=ru (api.theunum.io).
# Bootstrap только если БД пуста и sync с theunum ещё не прошёл.
DEFAULT_BOOTSTRAP_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("79a3a5fb-b491-570f-a5d5-5814eafbeb46", "crypto", "Криптовалюта"),
    ("e160f847-958d-59a0-bedf-0a6f9510a017", "economics", "Экономика"),
    ("5c335bb3-73cc-5038-b62c-9008aefb475d", "finance", "Финансы"),
    ("3796800f-ca41-511b-af50-f278a674902c", "technology", "Технологии"),
    ("67f8a979-9d6c-5fd6-ab4b-fe777553d219", "world", "Мир"),
    ("ae4f2ef9-e9d7-5045-a447-d9f5fe09fa93", "ai", "ИИ"),
)

# Старые slug из LLM / черновиков → актуальные slug CMS.
_LEGACY_SLUG_ALIASES: dict[str, str] = {
    "cryptocurrency": "crypto",
    "economy": "economics",
}

EDITORIAL_TOPIC_TO_SITE: dict[str, str] = {
    "Криптовалюты и цифровые активы": "crypto",
    "Децентрализованные финансы (DeFi)": "crypto",
    "Технология блокчейна и Web3": "crypto",
    "NFT и токеномика": "crypto",
    "Майнинг и стейкинг": "crypto",
    "Биржи и кошельки": "crypto",
    "Финтех и платежные системы": "finance",
    "Нормативно-правовое регулирование цифровых активов": "finance",
    "Финансовые и экономические события": "economics",
    "Цифровая безопасность и защита данных": "technology",
}

_SLUG_HINTS: tuple[tuple[str, str], ...] = (
    ("cryptocurrency", "crypto"),
    ("bitcoin", "crypto"),
    ("ethereum", "crypto"),
    ("defi", "crypto"),
    ("blockchain", "crypto"),
    ("mining", "crypto"),
    ("exchange", "crypto"),
    ("stablecoin", "crypto"),
    ("econom", "economics"),
    ("macro", "economics"),
    ("inflation", "economics"),
    ("gdp", "economics"),
    ("financ", "finance"),
    ("bank", "finance"),
    ("stock", "finance"),
    ("ipo", "finance"),
    ("treasury", "finance"),
    ("regulat", "finance"),
    ("machine-learning", "ai"),
    ("artificial-intelligence", "ai"),
    ("openai", "ai"),
    ("chatgpt", "ai"),
    ("tech", "technology"),
    ("software", "technology"),
    ("hack", "technology"),
    ("security", "technology"),
    ("malware", "technology"),
)

_TEXT_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(bitcoin|btc|ethereum|eth|crypto|defi|stablecoin|altcoin)\b", re.I), "crypto"),
    (re.compile(r"\b(blockchain|web3|nft|mining|staking|validator)\b", re.I), "crypto"),
    (re.compile(r"\b(inflation|gdp|macroeconom|central bank|interest rate)\b", re.I), "economics"),
    (re.compile(r"(экономик|инфляц|центробанк|цб рф|ставк)", re.I), "economics"),
    (re.compile(r"\b(bank|ipo|stock|shares|treasury|sec\b|cftc|regulat)\b", re.I), "finance"),
    (re.compile(r"(банк|акци|бирж|регулятор|лиценз)", re.I), "finance"),
    (
        re.compile(
            r"\b(openai|chatgpt|llm|machine learning|artificial intelligence|generative ai)\b",
            re.I,
        ),
        "ai",
    ),
    (re.compile(r"(нейросет|искусственн(ый|ого) интеллект|языков(ая|ые) модел)", re.I), "ai"),
    (re.compile(r"\b(apple|google|microsoft|software|hack|malware)\b", re.I), "technology"),
    (re.compile(r"(технолог|взлом|хакер)", re.I), "technology"),
)


def _normalize_slug(raw: str | None) -> str:
    if not raw:
        return ""
    slug = raw.strip().lower().replace("_", "-")
    slug = re.sub(r"[^a-z0-9-]+", "-", slug)
    return re.sub(r"-+", "-", slug).strip("-")


def _canonical_slug(slug: str, allowed: frozenset[str]) -> str | None:
    if slug in allowed:
        return slug
    aliased = _LEGACY_SLUG_ALIASES.get(slug)
    if aliased and aliased in allowed:
        return aliased
    return None


def active_site_categories(db: Session) -> list[TagCategoryCache]:
    return list(
        db.scalars(
            select(TagCategoryCache)
            .where(
                TagCategoryCache.kind == TagCategoryKind.CATEGORY,
                TagCategoryCache.is_active.is_(True),
            )
            .order_by(TagCategoryCache.slug)
        ).all()
    )


def active_site_category_slugs(db: Session) -> frozenset[str]:
    return frozenset(row.slug for row in active_site_categories(db))


def bootstrap_site_categories_if_empty(db: Session) -> int:
    if active_site_category_slugs(db):
        return 0
    for category_id, slug, name_ru in DEFAULT_BOOTSTRAP_CATEGORIES:
        db.add(
            TagCategoryCache(
                id=category_id,
                kind=TagCategoryKind.CATEGORY,
                slug=slug,
                name_ru=name_ru,
                name_en=slug.replace("-", " ").title(),
                is_active=True,
            )
        )
    db.flush()
    return len(DEFAULT_BOOTSTRAP_CATEGORIES)


def is_valid_site_category_slug(db: Session, slug: str | None) -> bool:
    """True if slug is one of the active CMS category slugs in Postgres."""
    if not slug:
        return False
    if not active_site_category_slugs(db):
        bootstrap_site_categories_if_empty(db)
    allowed = active_site_category_slugs(db)
    normalized = _normalize_slug(slug)
    return normalized in allowed or _LEGACY_SLUG_ALIASES.get(normalized) in allowed


def get_fallback_slug(db: Session) -> str:
    configured = str(get_setting(db, FALLBACK_SLUG_SETTING, "world") or "world")
    slugs = active_site_category_slugs(db)
    if configured in slugs:
        return configured
    if "world" in slugs:
        return "world"
    return sorted(slugs)[0] if slugs else "world"


def _pick_allowed(candidate: str | None, allowed: frozenset[str], fallback: str) -> str:
    if candidate:
        canonical = _canonical_slug(candidate, allowed)
        if canonical:
            return canonical
    return fallback if fallback in allowed else (sorted(allowed)[0] if allowed else "world")


def _match_slug_hints(slug: str, allowed: frozenset[str]) -> str | None:
    for hint, category in _SLUG_HINTS:
        if hint in slug:
            canonical = _canonical_slug(category, allowed)
            if canonical:
                return canonical
    return None


def _match_text_hints(text: str, allowed: frozenset[str]) -> str | None:
    for pattern, category in _TEXT_HINTS:
        if pattern.search(text):
            canonical = _canonical_slug(category, allowed)
            if canonical:
                return canonical
    return None


def resolve_site_category_slug(
    llm_slug: str | None,
    *,
    db: Session,
    editorial_topic: str | None = None,
    hint_text: str = "",
) -> str:
    """Map LLM / editorial context to an active category slug from Postgres."""
    if not active_site_category_slugs(db):
        bootstrap_site_categories_if_empty(db)

    allowed = active_site_category_slugs(db)
    fallback = get_fallback_slug(db)
    normalized = _normalize_slug(llm_slug)

    canonical = _canonical_slug(normalized, allowed)
    if canonical:
        return canonical

    from_hint = _match_slug_hints(normalized, allowed)
    if from_hint:
        return from_hint

    if editorial_topic and editorial_topic in EDITORIAL_TOPIC_TO_SITE:
        mapped = EDITORIAL_TOPIC_TO_SITE[editorial_topic]
        picked = _pick_allowed(mapped, allowed, fallback)
        if picked != fallback or _canonical_slug(mapped, allowed):
            return picked

    from_text = _match_text_hints(hint_text, allowed)
    if from_text:
        return from_text

    return fallback


def site_category_prompt_block(db: Session) -> str:
    rows = active_site_categories(db)
    if not rows:
        bootstrap_site_categories_if_empty(db)
        rows = active_site_categories(db)

    fallback = get_fallback_slug(db)
    lines = [
        "КАТЕГОРИЯ САЙТА (suggested_category_slug) — строго ОДИН slug из списка CMS theunum.io:",
    ]
    for row in rows:
        label = row.name_ru or row.name_en or row.slug
        suffix = " (fallback)" if row.slug == fallback else ""
        lines.append(f'- "{row.slug}" — {label}{suffix}')
    lines.extend(
        [
            "Правила:",
            f'- Если материал не подходит ни под одну тематическую категорию — "{fallback}".',
            "Запрещено придумывать другие slug (defi, security, ethereum-treasury и т.п.).",
        ]
    )
    return "\n".join(lines)


# Back-compat for tests / imports expecting a static tuple before sync.
SITE_CATEGORY_SLUGS: tuple[str, ...] = tuple(slug for _, slug, _ in DEFAULT_BOOTSTRAP_CATEGORIES)
