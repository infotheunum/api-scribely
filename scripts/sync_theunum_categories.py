"""Manual sync of site categories from api.theunum.io → tag_category_cache.

Usage:
  cd services/worker && uv run python ../../scripts/sync_theunum_categories.py
"""

from __future__ import annotations

import json
import sys

from common.site_category_sync import run_theunum_categories_sync
from db.session import make_engine, make_session_factory
from worker_app.settings import WorkerSettings


def main() -> int:
    settings = WorkerSettings()
    import os

    token = settings.theunum_api_token.strip() or os.environ.get("THEUNUM_INTEGRATION_TOKEN", "")
    db = make_session_factory(make_engine(settings.database_url))()
    try:
        stats = run_theunum_categories_sync(
            db,
            base_url=settings.theunum_api_base_url,
            path=settings.theunum_categories_path,
            api_token=token,
        )
        db.commit()
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        db.rollback()
        print(f"sync failed: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
