from __future__ import annotations

from db.app_settings import get_setting
from db.models import Draft, NewsCluster
from sqlalchemy.orm import Session
from worker_app.dedup.embeddings import cosine_similarity, embed_text, embedding_text

# Deliberately much higher than dedup's clustering threshold (0.6,
# "same event") — this gate is asking a different question ("is the
# rewrite basically a copy of one specific source"), which is a much
# higher bar. No local calibration data for this specific check yet
# (unlike the 0.6 clustering threshold, which has real EN/RU pair
# numbers behind it, embeddings.py) — 0.92 is a reasoned starting point,
# expected to be tuned via Admin Settings (ТЗ §4.21) once real editorial
# judgment on borderline cases is available.
DEFAULT_SIMILARITY_GATE_THRESHOLD = 0.92
SIMILARITY_GATE_SETTING_KEY = "compliance.similarity_gate_threshold"


def max_similarity_to_sources(cluster: NewsCluster, draft: Draft) -> float:
    """Highest cosine similarity between the EN rewrite and any single
    source RawItem in the cluster — the worst-case (closest-copy) match
    is what indicates paraphrase risk, not an average across sources."""
    if not draft.body_en:
        return 0.0
    draft_vector = embed_text(embedding_text(draft.title_en, draft.body_en))
    best = 0.0
    for item in cluster.raw_items:
        if not item.body:
            continue
        item_vector = embed_text(embedding_text(item.title, item.body))
        best = max(best, cosine_similarity(draft_vector, item_vector))
    return best


def similarity_gate_triggered(
    db: Session, cluster: NewsCluster, draft: Draft
) -> tuple[bool, float]:
    threshold = get_setting(db, SIMILARITY_GATE_SETTING_KEY, DEFAULT_SIMILARITY_GATE_THRESHOLD)
    score = max_similarity_to_sources(cluster, draft)
    return score >= threshold, score
