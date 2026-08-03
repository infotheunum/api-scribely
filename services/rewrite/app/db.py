from __future__ import annotations

from functools import lru_cache

from db.session import make_engine, make_session_factory
from rewrite_app.settings import RewriteSettings
from sqlalchemy.orm import Session


@lru_cache
def _session_factory():
    settings = RewriteSettings()
    engine = make_engine(settings.database_url)
    return make_session_factory(engine)


def new_session() -> Session:
    """rewrite's only DB usage is narrow and self-contained: rotation
    state/usage counters and bootstrapping PromptVersion (ТЗ §4.13) —
    Draft/RawItem/NewsCluster stay owned by api/worker (ТЗ §6.6)."""
    return _session_factory()()
