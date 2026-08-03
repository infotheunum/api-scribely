from __future__ import annotations

from functools import lru_cache

# Multilingual (50+ languages incl. EN/RU), small enough for CPU
# inference at MVP volume (~100-300 items/day, ТЗ §5). Computed locally,
# never through OpenRouter (План §4 — this is an internal technical
# operation, not something to spend free-tier LLM budget on).
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# Empirically: same-event EN/RU pairs score ~0.75-0.85 cosine similarity
# with this model, unrelated crypto-news pairs score ~0.30-0.40 — 0.6
# sits comfortably in the gap (see commit history for the calibration
# numbers this was picked from).
SIMILARITY_THRESHOLD = 0.6

# How many characters of title+body feed the embedding — full articles
# would work but add nothing past a point and slow inference for no
# benefit; the lede carries the "what event is this" signal.
EMBED_TEXT_CHARS = 500


@lru_cache
def _model():
    # Imported lazily so importing this module doesn't force a
    # multi-second sentence-transformers/torch import for callers that
    # only need the pure functions below (e.g. tests mocking embed_text).
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def embedding_text(title: str, body: str | None) -> str:
    text = title or ""
    if body:
        text = f"{text}\n{body}"
    return text[:EMBED_TEXT_CHARS]


def embed_text(text: str) -> list[float]:
    vector = _model().encode(text, normalize_embeddings=True)
    return vector.tolist()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    # Vectors are already normalized by embed_text (normalize_embeddings
    # =True), so dot product alone is the cosine similarity.
    return sum(x * y for x, y in zip(a, b, strict=True))
