from __future__ import annotations

import logging
import sys

from common.tracing import get_trace_id


class _TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id()
        return True


def configure_logging(service_name: str, level: str = "INFO") -> None:
    """Configures stdlib logging so every log line carries trace_id and
    the emitting service name (ТЗ §4.20) — Railway captures stdout/stderr
    directly, no separate log shipper needed in MVP."""
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_TraceIdFilter())
    handler.setFormatter(
        logging.Formatter(
            fmt=(
                f"%(asctime)s %(levelname)s [{service_name}] "
                "trace_id=%(trace_id)s %(name)s: %(message)s"
            )
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
