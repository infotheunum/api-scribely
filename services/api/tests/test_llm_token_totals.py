from __future__ import annotations

from common.llm_token_totals import load_token_totals, record_token_usage
from common.token_usage import TokenUsage, parse_anthropic_usage, parse_openai_compatible_usage


def test_parse_openai_usage():
    usage = parse_openai_compatible_usage(
        {"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
    )
    assert usage == TokenUsage(10, 5, 15)


def test_parse_anthropic_usage():
    usage = parse_anthropic_usage({"usage": {"input_tokens": 3, "output_tokens": 4}})
    assert usage == TokenUsage(3, 4, 7)


def test_record_token_totals(clean_db):
    record_token_usage(clean_db, TokenUsage(100, 50, 150), calls=2)
    clean_db.commit()
    totals = load_token_totals(clean_db)
    assert totals == {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "calls": 2,
    }
    record_token_usage(clean_db, TokenUsage(1, 1, 2), calls=1)
    clean_db.commit()
    totals = load_token_totals(clean_db)
    assert totals["total_tokens"] == 152
    assert totals["calls"] == 3
