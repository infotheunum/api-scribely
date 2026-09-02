"""Background regen loop with live progress in the log.

Regenerates one short-body draft per iteration (body < BODY_MIN_CHARS),
clears draft_export_log, sleeps between attempts.

Usage:
  nohup python scripts/run_regen_loop.py > /tmp/regen.log 2>&1 &
  tail -f /tmp/regen.log

Verbose lines (flush immediately):
  [2026-09-01 17:10:00] queue remaining=276 | ok=0 fail=0
  [2026-09-01 17:10:00] START draft=uuid en=450 ru=420 | Old title here...
  [2026-09-01 17:12:30] OK   draft=uuid status=ready_for_review en=2100 ru=2050 | New title...
  [2026-09-01 17:12:30] FAIL draft=uuid | OpenRouter error...
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime

from db.session import make_engine, make_session_factory
from worker_app.dispatch.regenerate import (
    count_drafts_for_regeneration,
    run_regenerate_batch,
    select_drafts_for_regeneration,
)
from worker_app.settings import WorkerSettings


def _ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _log(message: str) -> None:
    print(f"[{_ts()}] {message}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate short drafts with live progress")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Regenerate all queue drafts, not only short bodies",
    )
    parser.add_argument(
        "--fail-sleep",
        type=int,
        default=600,
        help="Seconds to wait after a failed draft (default 600)",
    )
    parser.add_argument(
        "--ok-sleep",
        type=int,
        default=60,
        help="Seconds to wait after success (default 60)",
    )
    args = parser.parse_args()

    settings = WorkerSettings()
    db = make_session_factory(make_engine(settings.database_url))()
    ok_total = 0
    fail_total = 0
    iteration = 0

    try:
        initial = count_drafts_for_regeneration(db, all_queue=args.all)
        _log(
            f"regen loop started mode={'all_queue' if args.all else 'short_bodies'} "
            f"initial_queue={initial}"
        )

        while True:
            remaining = count_drafts_for_regeneration(db, all_queue=args.all)
            iteration += 1
            _log(
                f"tick #{iteration} remaining={remaining} | ok={ok_total} fail={fail_total} "
                f"progress={ok_total + fail_total}/{initial}"
            )
            if remaining == 0:
                _log(f"DONE ok={ok_total} fail={fail_total}")
                return 0

            pending = select_drafts_for_regeneration(db, all_queue=args.all, limit=1)
            if not pending:
                _log("queue empty (unexpected) — stopping")
                return 0

            draft = pending[0]
            _log(
                f"START draft={draft.id} status={draft.status} "
                f"en={len(draft.body_en or '')} ru={len(draft.body_ru or '')} | "
                f"{(draft.title_en or '')[:70]}"
            )

            result = run_regenerate_batch(
                db,
                settings=settings,
                all_queue=args.all,
                limit=1,
                clear_export=True,
            )

            for item in result.get("successes", []):
                ok_total += 1
                generated = item.get("content_generated_at", "")
                _log(
                    f"OK   draft={item['draft_id']} status={item['status']} "
                    f"en={item['body_en_len']} ru={item['body_ru_len']} "
                    f"generated={generated} | "
                    f"{item['title_en'][:70]}"
                )

            for item in result.get("errors", []):
                fail_total += 1
                err = item.get("error", "unknown error")
                if len(err) > 240:
                    err = err[:240] + "…"
                _log(f"FAIL draft={item['draft_id']} | {err}")

            left = result.get("remaining", remaining)
            _log(
                f"batch selected={result['selected']} regenerated={result['regenerated']} "
                f"failed={result['failed']} remaining={left}"
            )

            if result["failed"]:
                _log(f"sleep {args.fail_sleep}s after failure")
                time.sleep(args.fail_sleep)
            else:
                _log(f"sleep {args.ok_sleep}s after success")
                time.sleep(args.ok_sleep)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
