from __future__ import annotations

from worker_app.dedup.embeddings import (
    EMBED_TEXT_CHARS,
    cosine_similarity,
    embed_text,
    embed_texts,
    embedding_text,
)


def test_embedding_text_combines_title_and_body_and_truncates():
    text = embedding_text("Title", "Body " * 1000)
    assert text.startswith("Title\nBody")
    assert len(text) <= EMBED_TEXT_CHARS


def test_embedding_text_handles_missing_body():
    assert embedding_text("Just a title", None) == "Just a title"


def test_cosine_similarity_identical_vectors_is_one():
    v = [0.6, 0.8]
    assert abs(cosine_similarity(v, v) - 1.0) < 1e-9


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert abs(cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-9


def test_embed_texts_returns_one_vector_per_input(monkeypatch):
    import numpy as np

    class _FakeModel:
        def encode(self, texts, **kwargs):
            return np.array([[1.0, 0.0], [0.0, 1.0]][: len(texts)])

    monkeypatch.setattr("worker_app.dedup.embeddings._model", lambda: _FakeModel())

    vectors = embed_texts(["alpha", "beta"], batch_size=8)
    assert len(vectors) == 2
    assert vectors[0] == [1.0, 0.0]
    assert vectors[1] == [0.0, 1.0]
    assert embed_texts([]) == []


def test_real_model_scores_same_event_en_ru_higher_than_unrelated():
    """Slow (loads the real multilingual model, ~seconds on first call)
    on purpose — this is the actual claim the whole feature rests on:
    that a same-event EN/RU pair scores meaningfully higher than two
    unrelated EN articles. Everything else in this suite mocks embed_text
    and would happily pass even if the model were nonsense."""
    en_a = embed_text(
        embedding_text("Bitcoin surges past $120,000 as ETF inflows accelerate", None)
    )
    ru_a = embed_text(
        embedding_text("Биткоин превысил $120,000 на фоне роста притоков в ETF", None)
    )
    en_b = embed_text(
        embedding_text("Ethereum developers announce major protocol upgrade for next quarter", None)
    )

    same_event_score = cosine_similarity(en_a, ru_a)
    unrelated_score = cosine_similarity(en_a, en_b)

    assert same_event_score > 0.6
    assert same_event_score > unrelated_score + 0.2
