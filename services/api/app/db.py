from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from api_app.settings import ApiSettings
from db.session import make_engine, make_session_factory
from sqlalchemy.orm import Session


@lru_cache
def _session_factory():
    settings = ApiSettings()
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
