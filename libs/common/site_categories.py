from __future__ import annotations

import re

from db.app_settings import get_setting
from db.enums import TagCategoryKind
from db.models import Draft, TagCategoryCache
from sqlalchemy import select
from sqlalchemy.orm import Session

FALLBACK_SLUG_SETTING = "site_category.fallback_slug"

# Slugs и id = GET /api/v1/categories?locale=ru (api.theunum.io).
DEFAULT_BOOTSTRAP_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("79a3a5fb-b491-570f-a5d5-5814eafbeb46", "crypto", "Криптовалюта"),
    ("e160f847-958d-59a0-bedf-0a6f9510a017", "economics", "Экономика"),
    ("5c335bb3-73cc-5038-b62c-9008aefb475d", "finance", "Финансы"),
    ("3796800f-ca41-511b-af50-f278a674902c", "technology", "Технологии"),
    ("67f8a979-9d6c-5fd6-ab4b-fe777553d219", "world", "Мир"),
    ("ae4f2ef9-e9d7-5045-a447-d9f5fe09fa93", "ai", "ИИ"),
)

# Любой «мусорный» / старый slug → канонический slug CMS.
# Канонические slug всегда берутся из Postgres (sync / bootstrap).
STATIC_SLUG_ALIASES: dict[str, str] = {
    # crypto
    "cryptocurrency": "crypto",
    "cryptocurrencies": "crypto",
    "crypto-currency": "crypto",
    "digital-assets": "crypto",
    "digital-asset": "crypto",
    "defi": "crypto",
    "de-fi": "crypto",
    "blockchain": "crypto",
    "web3": "crypto",
    "web-3": "crypto",
    "nft": "crypto",
    "nfts": "crypto",
    "bitcoin": "crypto",
    "btc": "crypto",
    "ethereum": "crypto",
    "eth": "crypto",
    "ethereum-treasury": "crypto",
    "altcoin": "crypto",
    "altcoins": "crypto",
    "stablecoin": "crypto",
    "stablecoins": "crypto",
    "mining": "crypto",
    "staking": "crypto",
    "exchange": "crypto",
    "exchanges": "crypto",
    "wallet": "crypto",
    "wallets": "crypto",
    # economics
    "economy": "economics",
    "macro": "economics",
    "macroeconomics": "economics",
    "macro-economics": "economics",
    # finance
    "financial": "finance",
    "fintech": "finance",
    "banking": "finance",
    "bank": "finance",
    "banks": "finance",
    "stock": "finance",
    "stocks": "finance",
    "equity": "finance",
    "equities": "finance",
    "ipo": "finance",
    "treasury": "finance",
    "markets": "finance",
    "market": "finance",
    "regulation": "finance",
    "regulatory": "finance",
    # technology
    "tech": "technology",
    "technology-news": "technology",
    "software": "technology",
    "security": "technology",
    "cybersecurity": "technology",
    "cyber-security": "technology",
    "hack": "technology",
    "hacking": "technology",
    "malware": "technology",
    # ai
    "artificial-intelligence": "ai",
    "machine-learning": "ai",
    "ml": "ai",
    "llm": "ai",
    "llms": "ai",
    "openai": "ai",
    "chatgpt": "ai",
    "generative-ai": "ai",
    # world
    "geopolitics": "world",
    "geopolitical": "world",
    "politics": "world",
    "political": "world",
    "global": "world",
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

_SLUG_HINTS: tuple[tuple[str, str], ...] = tuple(
    sorted(STATIC_SLUG_ALIASES.items(), key=lambda pair: (-len(pair[0]), pair[0]))
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


def _static_aliases_for_canonical(canonical: str) -> list[str]:
    return sorted(alias for alias, target in STATIC_SLUG_ALIASES.items() if target == canonical)


def slug_alias_map(db: Session) -> dict[str, str]:
    """alias (normalized) → canonical active slug."""
    if not active_site_category_slugs(db):
        bootstrap_site_categories_if_empty(db)

    allowed = active_site_category_slugs(db)
    mapping: dict[str, str] = {}

    for row in active_site_categories(db):
        mapping[row.slug] = row.slug
        for alias in row.aliases or []:
            normalized = _normalize_slug(alias)
            if normalized:
                mapping[normalized] = row.slug

    for alias, canonical in STATIC_SLUG_ALIASES.items():
        normalized_alias = _normalize_slug(alias)
        if normalized_alias and canonical in allowed:
            mapping[normalized_alias] = canonical

    return mapping


def canonicalize_site_category_slug(raw: str | None, db: Session) -> str | None:
    """Map raw slug / alias to active CMS slug, or None if unknown."""
    normalized = _normalize_slug(raw)
    if not normalized:
        return None
    if not active_site_category_slugs(db):
        bootstrap_site_categories_if_empty(db)
    return slug_alias_map(db).get(normalized)


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
                aliases=_static_aliases_for_canonical(slug),
                is_active=True,
            )
        )
    db.flush()
    return len(DEFAULT_BOOTSTRAP_CATEGORIES)


def is_valid_site_category_slug(db: Session, slug: str | None) -> bool:
    """True if slug resolves to an active CMS category."""
    if not slug:
        return False
    if not active_site_category_slugs(db):
        bootstrap_site_categories_if_empty(db)
    return canonicalize_site_category_slug(slug, db) is not None


def get_fallback_slug(db: Session) -> str:
    configured = str(get_setting(db, FALLBACK_SLUG_SETTING, "world") or "world")
    slugs = active_site_category_slugs(db)
    if configured in slugs:
        return configured
    if "world" in slugs:
        return "world"
    return sorted(slugs)[0] if slugs else "world"


def _pick_allowed(candidate: str | None, allowed: frozenset[str], fallback: str, db: Session) -> str:
    if candidate:
        canonical = canonicalize_site_category_slug(candidate, db)
        if canonical and canonical in allowed:
            return canonical
    return fallback if fallback in allowed else (sorted(allowed)[0] if allowed else "world")


def _match_slug_hints(slug: str, allowed: frozenset[str], db: Session) -> str | None:
    for hint, category in _SLUG_HINTS:
        if hint in slug:
            canonical = canonicalize_site_category_slug(category, db)
            if canonical and canonical in allowed:
                return canonical
    return None


def _match_text_hints(text: str, allowed: frozenset[str], db: Session) -> str | None:
    for pattern, category in _TEXT_HINTS:
        if pattern.search(text):
            canonical = canonicalize_site_category_slug(category, db)
            if canonical and canonical in allowed:
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

    canonical = canonicalize_site_category_slug(normalized, db)
    if canonical and canonical in allowed:
        return canonical

    from_hint = _match_slug_hints(normalized, allowed, db)
    if from_hint:
        return from_hint

    if editorial_topic and editorial_topic in EDITORIAL_TOPIC_TO_SITE:
        mapped = EDITORIAL_TOPIC_TO_SITE[editorial_topic]
        picked = _pick_allowed(mapped, allowed, fallback, db)
        if picked != fallback or canonicalize_site_category_slug(mapped, db):
            return picked

    from_text = _match_text_hints(hint_text, allowed, db)
    if from_text:
        return from_text

    return fallback


def reconcile_draft_category_slugs(db: Session) -> dict[str, int]:
    """Rewrite pending_category_slug on all drafts to canonical CMS slugs."""
    scanned = 0
    changed = 0
    for draft in db.scalars(select(Draft).where(Draft.pending_category_slug.is_not(None))).all():
        scanned += 1
        old = draft.pending_category_slug
        hint = " ".join(
            part
            for part in (draft.title_en, draft.body_en, draft.title_ru, draft.body_ru, old or "")
            if part
        )
        new = resolve_site_category_slug(old, db=db, hint_text=hint)
        if old != new:
            draft.pending_category_slug = new
            changed += 1
    return {"drafts_scanned": scanned, "drafts_changed": changed}


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
            "Используй только slug из списка выше — синонимы вроде cryptocurrency/economy не принимаются.",
        ]
    )
    return "\n".join(lines)


SITE_CATEGORY_SLUGS: tuple[str, ...] = tuple(slug for _, slug, _ in DEFAULT_BOOTSTRAP_CATEGORIES)

# Back-compat alias used in tests / older imports.
_LEGACY_SLUG_ALIASES = STATIC_SLUG_ALIASES
