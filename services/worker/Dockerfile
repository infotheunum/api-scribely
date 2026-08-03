# Build context is the REPO ROOT (Railway service config: Root Directory
# stays at "/", Dockerfile Path = services/worker/Dockerfile).
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.1 /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock .python-version /app/
COPY libs /app/libs
COPY proto /app/proto
COPY scripts/gen_proto.sh /app/scripts/gen_proto.sh
COPY services/worker /app/services/worker

RUN uv sync --frozen --package unum-worker
ENV PATH="/app/.venv/bin:$PATH"

RUN PYTHON_BIN=/app/.venv/bin/python bash scripts/gen_proto.sh

ENV PYTHONUNBUFFERED=1
EXPOSE 8001

CMD ["sh", "-c", "uvicorn worker_app.main:app --host 0.0.0.0 --port ${PORT:-8001}"]
