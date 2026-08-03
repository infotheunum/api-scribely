#!/usr/bin/env bash
# Regenerate gRPC/protobuf stubs from proto/ into libs/grpc_gen/.
#
# Output is NOT committed (see .gitignore) — every service Dockerfile and
# local dev setup must run this before the app can import `scribely.*`
# (ТЗ §6.6: proto/ is the contract, libs/grpc_gen/ is a build artifact).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROTO_DIR="$REPO_ROOT/proto"
OUT_DIR="$REPO_ROOT/libs/grpc_gen"
PYTHON_BIN="${PYTHON_BIN:-python3}"

mkdir -p "$OUT_DIR/scribely/rewrite/v1"

"$PYTHON_BIN" -m grpc_tools.protoc \
  -I "$PROTO_DIR" \
  --python_out="$OUT_DIR" \
  --grpc_python_out="$OUT_DIR" \
  --pyi_out="$OUT_DIR" \
  "$PROTO_DIR/scribely/rewrite/v1/rewrite.proto"

# grpc_tools.protoc does not emit __init__.py for intermediate packages.
find "$OUT_DIR/scribely" -type d -exec touch {}/__init__.py \;

echo "Generated gRPC stubs into $OUT_DIR/scribely/rewrite/v1/"
