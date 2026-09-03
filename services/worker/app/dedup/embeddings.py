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

DEFAULT_EMBED_BATCH_SIZE = 32
EMBED_BATCH_SIZE_SETTING_KEY = "dedup.embed_batch_size"


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


def embed_texts(
    texts: list[str],
    *,
    batch_size: int = DEFAULT_EMBED_BATCH_SIZE,
) -> list[list[float]]:
    """Encode many texts in one model pass (much faster than per-item on CPU)."""
    if not texts:
        return []
    import numpy as np

    vectors = _model().encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    arr = np.atleast_2d(np.asarray(vectors))
    return [row.tolist() for row in arr]


def embed_text(text: str) -> list[float]:
    return embed_texts([text], batch_size=1)[0]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    # Vectors are already normalized by embed_text (normalize_embeddings
    # =True), so dot product alone is the cosine similarity.
    return sum(x * y for x, y in zip(a, b, strict=True))
