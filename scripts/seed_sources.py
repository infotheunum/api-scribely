"""Seeds the Source table from the ✅-verified subset of
docs/Реестр_Источников_Технический_Черновик.md (План §3, Фаза 1).

Idempotent — safe to run repeatedly (matches on url). URLs were
live-verified with curl on 2026-08-03 (see registry doc for details,
incl. the Bloomberg Crypto feed found dead and dropped from this list).
Investing.com RU feeds were live-verified 2026-09-03 from
https://ru.investing.com/webmaster-tools/rss (all 30 returned
application/rss+xml; broker promo feeds are not seeded).
CoinJournal feeds were live-verified 2026-09-03 from
https://coinjournal.net/feeds/.

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

# Каталог https://ru.investing.com/webmaster-tools/rss, live 2026-09-03.
# Не сидим: brokers.rss / brokers_promotions.rss / brokers_press.rss /
# brokers_interviews.rss — промо брокеров, не редакционный поток.
# news.rss («Все Новости») — зонтик над news_*; кластерный дедуп его
# переварит, но лишний poll+embedding на каждую статью ни к чему.
INVESTING_RU_POLL_SECONDS = 1800
INVESTING_RU_SOURCES = [
    (
        "Investing.com RU — Аналитика: Самое популярное",
        "https://ru.investing.com/rss/286.rss",
    ),
    (
        "Investing.com RU — Аналитика: Выбор редакции",
        "https://ru.investing.com/rss/290.rss",
    ),
    (
        "Investing.com RU — Аналитика: Обзор рынка",
        "https://ru.investing.com/rss/market_overview.rss",
    ),
    (
        "Investing.com RU — Аналитика: Рынки акций",
        "https://ru.investing.com/rss/stock.rss",
    ),
    (
        "Investing.com RU — Аналитика: Форекс",
        "https://ru.investing.com/rss/forex.rss",
    ),
    (
        "Investing.com RU — Аналитика: Сырьевые товары",
        "https://ru.investing.com/rss/commodities.rss",
    ),
    (
        "Investing.com RU — Аналитика: Криптовалюты",
        "https://ru.investing.com/rss/302.rss",
    ),
    (
        "Investing.com RU — Аналитика: Облигации",
        "https://ru.investing.com/rss/bonds.rss",
    ),
    (
        "Investing.com RU — Аналитика: ETF",
        "https://ru.investing.com/rss/320.rss",
    ),
    (
        "Investing.com RU — Новости: Самое популярное",
        "https://ru.investing.com/rss/news_285.rss",
    ),
    (
        "Investing.com RU — Новости валютного рынка",
        "https://ru.investing.com/rss/news_1.rss",
    ),
    (
        "Investing.com RU — Новости фьючерсов и сырья",
        "https://ru.investing.com/rss/news_11.rss",
    ),
    (
        "Investing.com RU — Новости фондовых рынков",
        "https://ru.investing.com/rss/news_25.rss",
    ),
    (
        "Investing.com RU — Новости экономики",
        "https://ru.investing.com/rss/news_14.rss",
    ),
    (
        "Investing.com RU — Новости России и соседей",
        "https://ru.investing.com/rss/news_12.rss",
    ),
    (
        "Investing.com RU — Экономические показатели",
        "https://ru.investing.com/rss/news_95.rss",
    ),
    (
        "Investing.com RU — Новости криптовалют",
        "https://ru.investing.com/rss/news_301.rss",
    ),
    (
        "Investing.com RU — Новости мира",
        "https://ru.investing.com/rss/news_287.rss",
    ),
    (
        "Investing.com RU — Новости компаний",
        "https://ru.investing.com/rss/news_356.rss",
    ),
    (
        "Investing.com RU — Новости инсайдерских торгов",
        "https://ru.investing.com/rss/news_357.rss",
    ),
    (
        "Investing.com RU — Рейтинги биржевых аналитиков",
        "https://ru.investing.com/rss/news_1061.rss",
    ),
    (
        "Investing.com RU — Отчеты о прибылях и слухи",
        "https://ru.investing.com/rss/news_1062.rss",
    ),
    (
        "Investing.com RU — Расшифровки отчетов о доходах",
        "https://ru.investing.com/rss/news_1063.rss",
    ),
    (
        "Investing.com RU — Формы SEC",
        "https://ru.investing.com/rss/news_1064.rss",
    ),
    (
        "Investing.com RU — Идеи для инвестиций",
        "https://ru.investing.com/rss/news_1065.rss",
    ),
]

# Каталог https://coinjournal.net/feeds/, live 2026-09-03.
# Не сидим: /news/feed/ (зонтик над category/*), tag-ленты Editor's Picks
# (bitcoin/ethereum/… — те же статьи), /news/crime/feed/ (404 на странице
# опечатка; живой URL — category/crime), featured (редирект на /zh/).
COINJOURNAL_POLL_SECONDS = 1800
COINJOURNAL_SOURCES = [
    (
        "CoinJournal — Analysis",
        "https://coinjournal.net/news/category/analysis/feed/",
    ),
    (
        "CoinJournal — Business",
        "https://coinjournal.net/news/category/business/feed/",
    ),
    (
        "CoinJournal — Crime",
        "https://coinjournal.net/news/category/crime/feed/",
    ),
    (
        "CoinJournal — Events",
        "https://coinjournal.net/news/category/events/feed/",
    ),
    (
        "CoinJournal — Interview",
        "https://coinjournal.net/news/category/interview/feed/",
    ),
    (
        "CoinJournal — Markets",
        "https://coinjournal.net/news/category/markets/feed/",
    ),
    (
        "CoinJournal — Opinion",
        "https://coinjournal.net/news/category/opinion/feed/",
    ),
    (
        "CoinJournal — Policy & Regulation",
        "https://coinjournal.net/news/category/policy-and-regulation/feed/",
    ),
    (
        "CoinJournal — Press Release",
        "https://coinjournal.net/news/category/press-release/feed/",
    ),
    (
        "CoinJournal — Surveys and Reports",
        "https://coinjournal.net/news/category/surveys-and-reports/feed/",
    ),
    (
        "CoinJournal — Technology",
        "https://coinjournal.net/news/category/technology/feed/",
    ),
]

MANUAL_SOURCE_NAME = "Manual Inject"
MANUAL_SOURCE_URL = "manual://inject"


def _add_rss(db, name: str, url: str, language: str, tier: SourceTier, poll_interval: int) -> None:
    existing = db.scalar(select(Source).where(Source.url == url))
    if existing:
        print(f"skip (exists): {name}")
        return
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


def seed(db) -> None:
    for name, url, language, tier, poll_interval in RSS_SOURCES:
        _add_rss(db, name, url, language, tier, poll_interval)

    for name, url in INVESTING_RU_SOURCES:
        _add_rss(
            db,
            name,
            url,
            "ru",
            SourceTier.TIER_4,
            INVESTING_RU_POLL_SECONDS,
        )

    for name, url in COINJOURNAL_SOURCES:
        _add_rss(
            db,
            name,
            url,
            "en",
            SourceTier.TIER_1,
            COINJOURNAL_POLL_SECONDS,
        )

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
