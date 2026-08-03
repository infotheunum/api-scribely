from __future__ import annotations

# Thin re-export: the channel-building mechanics are generic infra shared
# with worker (libs/common/grpc_client.py, ТЗ §6.6) — this module is where
# api-specific gRPC call wrappers will land as they're added in later
# phases (e.g. calling RewriteCluster from the Approve flow).
from common.grpc_client import build_rewrite_channel, check_rewrite_health, rewrite_stub

__all__ = ["build_rewrite_channel", "check_rewrite_health", "rewrite_stub"]
