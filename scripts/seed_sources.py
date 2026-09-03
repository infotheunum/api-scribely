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
Category catalog feeds (CMS: crypto/economics/finance/technology/world/ai)
were live-verified 2026-09-03 — 5–10 per category, see CATEGORY_RSS_SOURCES.

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

# Каталог по CMS-категориям theunum.io (libs/common/site_categories.py):
# crypto | economics | finance | technology | world | ai.
# Live curl 2026-09-03; URL уже из RSS_SOURCES / Investing / CoinJournal не дублируем.
# Цель — 5–10 лент на категорию (с учётом уже существующих crypto-сидов).
CATEGORY_RSS_SOURCES = [
    # --- crypto (Криптовалюта) ---
    ("The Block", "https://www.theblock.co/rss.xml", "en", SourceTier.TIER_1, 900),
    ("Blockworks", "https://blockworks.co/feed/", "en", SourceTier.TIER_1, 900),
    ("The Defiant", "https://thedefiant.io/api/feed", "en", SourceTier.TIER_1, 1200),
    ("CryptoPotato", "https://cryptopotato.com/feed", "en", SourceTier.TIER_1, 1200),
    ("AMBCrypto", "https://ambcrypto.com/feed", "en", SourceTier.TIER_1, 1200),
    ("U.Today", "https://u.today/rss", "en", SourceTier.TIER_1, 1200),
    ("Crypto.News", "https://crypto.news/feed/", "en", SourceTier.TIER_1, 1200),
    ("ForkLog", "https://forklog.com/feed/", "ru", SourceTier.TIER_1, 1800),
    ("Incrypted", "https://incrypted.com/feed/", "ru", SourceTier.TIER_1, 1800),
    ("Protos", "https://protos.com/feed/", "en", SourceTier.TIER_1, 1800),
    ("DL News", "https://www.dlnews.com/arc/outboundfeeds/rss/", "en", SourceTier.TIER_1, 1800),
    ("Bankless", "https://www.bankless.com/rss/feed", "en", SourceTier.TIER_1, 1800),
    # --- economics (Экономика) ---
    (
        "Federal Reserve — All Press",
        "https://www.federalreserve.gov/feeds/press_all.xml",
        "en",
        SourceTier.TIER_3,
        1800,
    ),
    (
        "Federal Reserve — Monetary Policy",
        "https://www.federalreserve.gov/feeds/press_monetary.xml",
        "en",
        SourceTier.TIER_3,
        1800,
    ),
    (
        "ECB Press",
        "https://www.ecb.europa.eu/rss/press.html",
        "en",
        SourceTier.TIER_3,
        1800,
    ),
    (
        "BIS Press Releases",
        "https://www.bis.org/doclist/all_pressrels.rss",
        "en",
        SourceTier.TIER_3,
        3600,
    ),
    (
        "BBC Business",
        "https://feeds.bbci.co.uk/news/business/rss.xml",
        "en",
        SourceTier.TIER_4,
        1800,
    ),
    # --- finance (Финансы / финтех / регуляторы) ---
    ("Finextra", "https://www.finextra.com/rss/headlines.aspx", "en", SourceTier.TIER_4, 1800),
    (
        "Finextra Blockchain",
        "https://www.finextra.com/rss/blogs.aspx?topic=Blockchain",
        "en",
        SourceTier.TIER_4,
        1800,
    ),
    ("PYMNTS", "https://www.pymnts.com/feed", "en", SourceTier.TIER_4, 1800),
    (
        "TechCrunch Fintech",
        "https://techcrunch.com/tag/fintech/feed/",
        "en",
        SourceTier.TIER_4,
        1800,
    ),
    (
        "Crunchbase Crypto",
        "https://news.crunchbase.com/sections/crypto/feed/",
        "en",
        SourceTier.TIER_4,
        1800,
    ),
    ("FSB News", "https://www.fsb.org/feed/", "en", SourceTier.TIER_3, 3600),
    ("Kraken Blog", "https://blog.kraken.com/feed", "en", SourceTier.TIER_5, 3600),
    # --- technology (Технологии / security) ---
    ("TechCrunch", "https://techcrunch.com/feed/", "en", SourceTier.TIER_4, 1800),
    (
        "Ars Technica Technology Lab",
        "https://feeds.arstechnica.com/arstechnica/technology-lab",
        "en",
        SourceTier.TIER_4,
        1800,
    ),
    ("The Verge", "https://www.theverge.com/rss/index.xml", "en", SourceTier.TIER_4, 1800),
    ("Krebs on Security", "https://krebsonsecurity.com/feed/", "en", SourceTier.TIER_4, 1800),
    (
        "The Hacker News",
        "https://feeds.feedburner.com/TheHackersNews",
        "en",
        SourceTier.TIER_4,
        1800,
    ),
    (
        "BleepingComputer",
        "https://www.bleepingcomputer.com/feed/",
        "en",
        SourceTier.TIER_4,
        1800,
    ),
    ("Wired", "https://www.wired.com/feed/rss", "en", SourceTier.TIER_4, 1800),
    (
        "BBC Technology",
        "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "en",
        SourceTier.TIER_4,
        1800,
    ),
    (
        "Chainalysis Blog",
        "https://blog.chainalysis.com/feed/",
        "en",
        SourceTier.TIER_5,
        3600,
    ),
    # --- world (Мир) ---
    (
        "BBC World",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "en",
        SourceTier.TIER_4,
        1800,
    ),
    (
        "Al Jazeera",
        "https://www.aljazeera.com/xml/rss/all.xml",
        "en",
        SourceTier.TIER_4,
        1800,
    ),
    ("NPR World", "https://feeds.npr.org/1004/rss.xml", "en", SourceTier.TIER_4, 1800),
    (
        "The Guardian World",
        "https://www.theguardian.com/world/rss",
        "en",
        SourceTier.TIER_4,
        1800,
    ),
    (
        "NYTimes World",
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "en",
        SourceTier.TIER_4,
        1800,
    ),
    # --- ai (ИИ) ---
    ("OpenAI Blog", "https://openai.com/blog/rss.xml", "en", SourceTier.TIER_5, 3600),
    (
        "Google AI Blog",
        "https://blog.google/technology/ai/rss/",
        "en",
        SourceTier.TIER_5,
        3600,
    ),
    (
        "Hugging Face Blog",
        "https://huggingface.co/blog/feed.xml",
        "en",
        SourceTier.TIER_5,
        3600,
    ),
    (
        "TechCrunch AI",
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "en",
        SourceTier.TIER_4,
        1800,
    ),
    (
        "MIT Technology Review",
        "https://www.technologyreview.com/feed/",
        "en",
        SourceTier.TIER_4,
        1800,
    ),
    (
        "The Verge AI",
        "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        "en",
        SourceTier.TIER_4,
        1800,
    ),
    ("MarkTechPost", "https://www.marktechpost.com/feed/", "en", SourceTier.TIER_4, 1800),
    ("Synced Review", "https://syncedreview.com/feed/", "en", SourceTier.TIER_4, 1800),
    (
        "Artificial Intelligence News",
        "https://artificialintelligence-news.com/feed/",
        "en",
        SourceTier.TIER_4,
        1800,
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

    for name, url, language, tier, poll_interval in CATEGORY_RSS_SOURCES:
        _add_rss(db, name, url, language, tier, poll_interval)

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
