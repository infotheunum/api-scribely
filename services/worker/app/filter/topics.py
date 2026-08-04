from __future__ import annotations

import re

from db.models import Topic
from sqlalchemy import select
from sqlalchemy.orm import Session

# Ten scopes verbatim from Редакционная_Политика_UNUM §1.4 — seed data
# for the `Topic` table (ТЗ §4.21) on first use only. From Фаза 5
# onward this dict is NOT the runtime source of truth anymore — edit
# topics/keywords through Admin Settings, not by changing this file.
# Each topic gets an EN+RU keyword set since sources are bilingual (ТЗ
# §4.2/§4.3) and RU headlines shouldn't silently fail to match
# categories that were only stocked with EN terms.
DEFAULT_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "Криптовалюты и цифровые активы": [
        "bitcoin",
        "btc",
        "ethereum",
        "\\beth\\b",
        "crypto",
        "cryptocurrency",
        "altcoin",
        "stablecoin",
        "digital asset",
        "tether",
        "\\busdt\\b",
        "\\busdc\\b",
        "криптовалют",
        "биткоин",
        "эфириум",
        "токен",
        "монет",
        "цифров(ой|ые) актив",
        "стейблкоин",
    ],
    "Децентрализованные финансы (DeFi)": [
        "\\bdefi\\b",
        "decentralized finance",
        "\\bdex\\b",
        "liquidity pool",
        "yield farming",
        "децентрализованн(ые|ых) финанс",
        "ликвидност",
        "пул ликвидности",
    ],
    "Технология блокчейна и Web3": [
        "blockchain",
        "\\bweb3\\b",
        "smart contract",
        "layer\\s?2",
        "\\bl2\\b",
        "блокчейн",
        "смарт-контракт",
        "распредел(ё|е)нн(ый|ого) реестр",
    ],
    "Финтех и платежные системы": [
        "fintech",
        "payment system",
        "cross-border payment",
        "remittance",
        "финтех",
        "платежн(ая|ой) систем",
        "трансграничн(ые|ых) платеж",
    ],
    "Нормативно-правовое регулирование цифровых активов": [
        "\\bsec\\b",
        "\\bcftc\\b",
        "regulat",
        "compliance",
        "legislation",
        "\\bmica\\b",
        "\\besma\\b",
        "\\bfca\\b",
        "\\biosco\\b",
        "sanction",
        "регулятор",
        "регулирован",
        "законодательств",
        "комплаенс",
        "лицензи",
        "санкци",
        "запрет",
    ],
    "Финансовые и экономические события": [
        "\\bmarket\\b",
        "\\beconomy\\b",
        "economic",
        "inflation",
        "interest rate",
        "\\bgdp\\b",
        "\\bipo\\b",
        "stocks?",
        "экономик",
        "\\bрынок\\b",
        "инфляц",
        "ставк(а|и)",
        "ввп",
        "акци[ияй]",
    ],
    "Цифровая безопасность и защита данных": [
        "\\bhack(ed|er)?\\b",
        "exploit",
        "breach",
        "vulnerabilit",
        "\\bsecurity\\b",
        "phishing",
        "взлом",
        "эксплойт",
        "уязвимост",
        "безопасност",
        "фишинг",
        "мошенничеств",
    ],
    "NFT и токеномика": [
        "\\bnft\\b",
        "non-fungible",
        "tokenomic",
        "токеномик",
        "невзаимозамен",
    ],
    "Майнинг и стейкинг": [
        "\\bmining\\b",
        "\\bminer\\b",
        "hashrate",
        "\\bstaking\\b",
        "validator",
        "proof-of-(stake|work)",
        "майнинг",
        "майнер",
        "стейкинг",
        "валидатор",
    ],
    "Биржи и кошельки": [
        "\\bexchange\\b",
        "\\bwallet\\b",
        "custody",
        "listing",
        "delisting",
        "withdrawal",
        "биржа",
        "кошел(ё|е)к",
        "кастоди",
        "листинг",
        "делистинг",
    ],
}

CompiledTopics = dict[str, list[re.Pattern]]


def _seed_default_topics(db: Session) -> list[Topic]:
    topics = [
        Topic(name=name, keywords=keywords, is_active=True)
        for name, keywords in DEFAULT_TOPIC_KEYWORDS.items()
    ]
    db.add_all(topics)
    db.flush()
    return topics


def active_topics(db: Session) -> dict[str, list[str]]:
    """Reads the current topic/keyword set from the `Topic` table (ТЗ
    §4.21), bootstrapping it from DEFAULT_TOPIC_KEYWORDS the first time
    the table is ever touched (same pattern as PromptVersion's v1
    bootstrap, Фаза 4). Unlike PromptVersion, an empty *active* set with
    rows already present is NOT re-seeded — an admin deliberately
    deactivating every topic is a valid state, not a gap to self-heal."""
    rows = db.scalars(select(Topic).where(Topic.is_active.is_(True))).all()
    if not rows and db.scalars(select(Topic)).first() is None:
        rows = _seed_default_topics(db)
        db.commit()
    return {row.name: row.keywords for row in rows}


def compile_topics(topics: dict[str, list[str]]) -> CompiledTopics:
    return {
        topic: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
        for topic, patterns in topics.items()
    }


def topic_hit_counts(text: str, compiled_topics: CompiledTopics) -> dict[str, int]:
    """Keyword hits per active topic in `text`. Rule-based on purpose —
    this is the funnel gate before any LLM spend happens (ТЗ §4.3), not a
    place to burn free-tier OpenRouter budget on classification."""
    return {
        topic: sum(1 for pattern in patterns if pattern.search(text))
        for topic, patterns in compiled_topics.items()
    }


def classify(text: str, compiled_topics: CompiledTopics) -> tuple[bool, str | None]:
    """Returns (in_topic, primary_topic). primary_topic is the active
    topic with the most keyword hits — ties broken by dict order."""
    if not compiled_topics:
        return False, None
    hits = topic_hit_counts(text, compiled_topics)
    best_topic = max(hits, key=lambda t: hits[t])
    if hits[best_topic] == 0:
        return False, None
    return True, best_topic
