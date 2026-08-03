from __future__ import annotations

import re

# Ten scopes verbatim from Редакционная_Политика_UNUM §1.4 — this list is
# the actual source of truth for "in topic or not", not something to
# improvise keywords for independently. Each gets an EN+RU keyword set
# since sources are bilingual (ТЗ §4.2/§4.3) and RU headlines shouldn't
# silently fail to match categories that were only stocked with EN terms.
TOPIC_KEYWORDS: dict[str, list[str]] = {
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

_COMPILED = {
    topic: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    for topic, patterns in TOPIC_KEYWORDS.items()
}


def topic_hit_counts(text: str) -> dict[str, int]:
    """Keyword hits per §1.4 topic in `text`. Rule-based on purpose — this
    is the funnel gate before any LLM spend happens (ТЗ §4.3), not a
    place to burn free-tier OpenRouter budget on classification."""
    return {
        topic: sum(1 for pattern in patterns if pattern.search(text))
        for topic, patterns in _COMPILED.items()
    }


def classify(text: str) -> tuple[bool, str | None]:
    """Returns (in_topic, primary_topic). primary_topic is the §1.4 scope
    with the most keyword hits — ties broken by dict order (i.e. by the
    order topics are listed in §1.4 itself)."""
    hits = topic_hit_counts(text)
    best_topic = max(hits, key=lambda t: hits[t])
    if hits[best_topic] == 0:
        return False, None
    return True, best_topic
