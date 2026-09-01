"""Background-friendly regen loop for Railway worker console.

Regenerates one short-body draft per iteration (body < 1800 chars),
clears draft_export_log, sleeps between attempts.

Usage:
  nohup python scripts/run_regen_loop.py > /tmp/regen.log 2>&1 &

  tail -f /tmp/regen.log
"""

from __future__ import annotations

import json
import sys
import time

from db.session import make_engine, make_session_factory
from worker_app.dispatch.regenerate import count_drafts_for_regeneration, run_regenerate_batch
from worker_app.settings import WorkerSettings


def main() -> int:
    settings = WorkerSettings()
    db = make_session_factory(make_engine(settings.database_url))()
    try:
        while True:
            left = count_drafts_for_regeneration(db, all_queue=False)
            print(f"remaining={left}", flush=True)
            if left == 0:
                print("DONE", flush=True)
                return 0
            result = run_regenerate_batch(
                db,
                settings=settings,
                all_queue=False,
                limit=1,
                clear_export=True,
            )
            print(json.dumps(result, ensure_ascii=False), flush=True)
            time.sleep(600 if result["failed"] else 60)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
