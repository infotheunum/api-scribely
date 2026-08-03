# Build context is the REPO ROOT (Railway service config: Root Directory
# stays at "/", Dockerfile Path = services/rewrite/Dockerfile) — this
# service needs sibling libs/ and proto/, not just its own subtree.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.1 /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock .python-version /app/
COPY libs /app/libs
COPY proto /app/proto
COPY scripts/gen_proto.sh /app/scripts/gen_proto.sh
COPY services/rewrite /app/services/rewrite

RUN uv sync --frozen --package unum-rewrite
ENV PATH="/app/.venv/bin:$PATH"

RUN PYTHON_BIN=/app/.venv/bin/python bash scripts/gen_proto.sh

ENV PYTHONUNBUFFERED=1
EXPOSE 50051

# Only reachable over Railway's private network (ТЗ §6.6, §8) — never
# expose this service's port publicly.
CMD ["python", "-m", "rewrite_app.server"]
