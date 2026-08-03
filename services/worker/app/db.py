from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from db.session import make_engine, make_session_factory
from sqlalchemy.orm import Session
from worker_app.settings import WorkerSettings


@lru_cache
def _session_factory():
    settings = WorkerSettings()
    engine = make_engine(settings.database_url)
    return make_session_factory(engine)


def get_db() -> Generator[Session, None, None]:
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def new_session() -> Session:
    """For the scheduler job, which isn't a FastAPI request — no
    dependency-injection generator involved, just a plain session per
    poll tick."""
    return _session_factory()()
