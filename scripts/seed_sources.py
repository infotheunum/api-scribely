"""Seeds the Source table from the ✅-verified subset of
docs/Реестр_Источников_Технический_Черновик.md (План §3, Фаза 1).

Idempotent — safe to run repeatedly (matches on url). URLs were
live-verified with curl on 2026-08-03 (see registry doc for details,
incl. the Bloomberg Crypto feed found dead and dropped from this list).

Usage: DATABASE_URL=... python scripts/seed_sources.py
"""

from __future__ import annotations

from common.settings import CommonSettings
from db.enums import SourceTier, SourceType
from db.models import Source
from db.session import make_engine, make_session_factory
from sqlalchemy import select

# (name, url, language, tier, poll_interval_seconds)
RSS_SOURCES = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", "en", SourceTier.TIER_1, 900),
    ("Cointelegraph", "https://cointelegraph.com/rss", "en", SourceTier.TIER_1, 900),
    ("Decrypt", "https://decrypt.co/feed", "en", SourceTier.TIER_1, 900),
    ("CryptoSlate", "https://cryptoslate.com/feed/", "en", SourceTier.TIER_1, 1200),
    ("Bitcoin Magazine", "https://bitcoinmagazine.com/feed", "en", SourceTier.TIER_1, 1200),
    ("BeInCrypto", "https://beincrypto.com/feed", "en", SourceTier.TIER_1, 900),
    ("NewsBTC", "https://www.newsbtc.com/feed/", "en", SourceTier.TIER_1, 1200),
    # RU source required for the cross-language dedup demo (План §4).
    ("BeInCrypto RU", "https://ru.beincrypto.com/feed", "ru", SourceTier.TIER_1, 1800),
    (
        "SEC Press Releases",
        "https://www.sec.gov/news/pressreleases.rss",
        "en",
        SourceTier.TIER_3,
        1800,
    ),
]

MANUAL_SOURCE_NAME = "Manual Inject"
MANUAL_SOURCE_URL = "manual://inject"


def seed(db) -> None:
    for name, url, language, tier, poll_interval in RSS_SOURCES:
        existing = db.scalar(select(Source).where(Source.url == url))
        if existing:
            print(f"skip (exists): {name}")
            continue
        db.add(
            Source(
                name=name,
                url=url,
                type=SourceType.RSS,
                tier=tier,
                language=language,
                poll_interval_seconds=poll_interval,
            )
        )
        print(f"added: {name}")

    existing_manual = db.scalar(select(Source).where(Source.type == SourceType.MANUAL))
    if existing_manual is None:
        db.add(
            Source(
                name=MANUAL_SOURCE_NAME,
                url=MANUAL_SOURCE_URL,
                type=SourceType.MANUAL,
                tier=SourceTier.TIER_1,
                language="en",
            )
        )
        print(f"added: {MANUAL_SOURCE_NAME}")
    else:
        print(f"skip (exists): {MANUAL_SOURCE_NAME}")

    db.commit()


def main() -> None:
    settings = CommonSettings()
    engine = make_engine(settings.database_url)
    session = make_session_factory(engine)()
    try:
        seed(session)
    finally:
        session.close()


if __name__ == "__main__":
    main()
