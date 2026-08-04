from __future__ import annotations

from worker_app.filter.topics import DEFAULT_TOPIC_KEYWORDS, classify, compile_topics

# Real headlines pulled from actual Decrypt/Cointelegraph RSS during
# local Phase 2 verification — genuine positives and genuine negatives,
# not invented examples. This is exactly the discrimination this filter
# exists for: Decrypt's general feed mixes crypto news with unrelated
# tech coverage.
REAL_IN_TOPIC_EXAMPLES = [
    "Bitcoin surges past $120,000 as ETF inflows accelerate",
    "Tether reports $1.5B Q2 profit as USDT supply grows",
    "SEC files new charges against crypto exchange for unregistered securities",
    "Coinbase misses Q2 earnings as crypto trading activity slows",
    "Биткоин превысил $120,000 на фоне роста притоков в ETF",
]
REAL_OUT_OF_TOPIC_EXAMPLES = [
    "Google Yanks Google Earth AI Image Tool Deepfake Fears",
    "FCC Bans Foreign Humanoid Robots China Roombas",
    "Suno AI Music Copyright Case Germany",
    "Researchers Tried Letting AI Do Science, It Failed",
]

COMPILED = compile_topics(DEFAULT_TOPIC_KEYWORDS)


def test_all_ten_redpolicy_scopes_are_present():
    # §1.4 of the editorial policy lists exactly ten scopes — this
    # dict is the actual seed data, so a silently-dropped category would
    # mean silently-rejected in-scope news on a fresh Topic table.
    assert len(DEFAULT_TOPIC_KEYWORDS) == 10


def test_real_in_topic_examples_pass():
    for text in REAL_IN_TOPIC_EXAMPLES:
        in_topic, topic = classify(text, COMPILED)
        assert in_topic, f"expected in-topic: {text!r}"
        assert topic is not None


def test_real_out_of_topic_examples_are_rejected():
    for text in REAL_OUT_OF_TOPIC_EXAMPLES:
        in_topic, topic = classify(text, COMPILED)
        assert not in_topic, f"expected out-of-topic: {text!r}"
        assert topic is None


def test_classify_picks_the_best_matching_topic():
    _, topic = classify("Bitcoin mining hashrate hits new high as miners add rigs", COMPILED)
    assert topic == "Майнинг и стейкинг"


def test_empty_text_is_out_of_topic():
    in_topic, topic = classify("", COMPILED)
    assert not in_topic
    assert topic is None
