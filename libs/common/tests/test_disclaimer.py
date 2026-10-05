"""Unit tests for publish disclaimer helper."""

from common.disclaimer import (
    DEFAULT_DISCLAIMER_RU,
    append_disclaimer,
    apply_disclaimer_to_bodies,
    resolve_disclaimer_variant,
)


def test_resolve_variant_by_category():
    assert resolve_disclaimer_variant("crypto") == "crypto"
    assert resolve_disclaimer_variant("ai") == "tech"
    assert resolve_disclaimer_variant("health") == "strict"
    assert resolve_disclaimer_variant(None) == "crypto"


def test_append_disclaimer_once():
    body = "Текст новости."
    once = append_disclaimer(body, DEFAULT_DISCLAIMER_RU)
    assert once.endswith(DEFAULT_DISCLAIMER_RU)
    twice = append_disclaimer(once, DEFAULT_DISCLAIMER_RU)
    assert twice.count(DEFAULT_DISCLAIMER_RU) == 1


def test_apply_disabled_leaves_body():
    en, ru = apply_disclaimer_to_bodies(
        None,
        body_en="EN body",
        body_ru="RU body",
        enabled=False,
    )
    assert en == "EN body"
    assert ru == "RU body"


def test_apply_enabled_appends_ru():
    _en, ru = apply_disclaimer_to_bodies(
        None,
        body_en="EN body",
        body_ru="RU body",
        enabled=True,
        category_slug="crypto",
    )
    assert DEFAULT_DISCLAIMER_RU in ru
