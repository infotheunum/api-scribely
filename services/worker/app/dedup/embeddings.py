from __future__ import annotations

import gc
import logging
import os
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

# A short RSS excerpt often contains only generic market language. Keep a
# fuller lede and the first details so differently worded coverage of one
# event still has enough shared semantic signal.
EMBED_TEXT_CHARS = 2_000

# The worker shares its small Railway container with ingestion, dispatch and
# the embedding model. Large transformer batches create a short-lived but
# substantial activation peak, so keep the default deliberately conservative.
DEFAULT_EMBED_BATCH_SIZE = 4
EMBED_BATCH_SIZE_SETTING_KEY = "dedup.embed_batch_size"

logger = logging.getLogger(__name__)

_TORCH_THREADS_CONFIGURED = False


def _configure_torch_threads() -> None:
    """Cap BLAS/torch thread fan-out — Railway bills CPU-minutes too."""
    global _TORCH_THREADS_CONFIGURED
    if _TORCH_THREADS_CONFIGURED:
        return
    threads = max(1, int(os.environ.get("WORKER_TORCH_NUM_THREADS", "1")))
    for key in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ.setdefault(key, str(threads))
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    try:
        import torch

        torch.set_num_threads(threads)
        if hasattr(torch, "set_num_interop_threads"):
            torch.set_num_interop_threads(1)
    except Exception:  # pragma: no cover - torch missing in some unit paths
        logger.debug("torch thread pin skipped", exc_info=True)
    _TORCH_THREADS_CONFIGURED = True


@lru_cache
def _model():
    # Imported lazily so importing this module doesn't force a
    # multi-second sentence-transformers/torch import for callers that
    # only need the pure functions below (e.g. tests mocking embed_text).
    _configure_torch_threads()
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def release_embedding_model() -> None:
    """Drop the cached SentenceTransformer so RSS can fall outside gen hours.

    Torch allocators may keep some arena memory, but clearing the model is
    still the largest controllable chunk of worker RAM (~$5+/period today).
    """
    _model.cache_clear()
    gc.collect()
    try:
        import torch

        if hasattr(torch, "cuda") and torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # pragma: no cover
        logger.debug("torch empty_cache skipped", exc_info=True)


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
