# Build context is the REPO ROOT (Railway service config: Root Directory
# stays at "/", Dockerfile Path = services/api/Dockerfile).
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.1 /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock .python-version alembic.ini /app/
COPY libs /app/libs
COPY proto /app/proto
COPY migrations /app/migrations
COPY scripts /app/scripts
COPY services/api /app/services/api

RUN uv sync --frozen --package unum-api
ENV PATH="/app/.venv/bin:$PATH"

RUN PYTHON_BIN=/app/.venv/bin/python bash scripts/gen_proto.sh

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Applies pending Alembic migrations, then seeds Source + the test
# Rewriter/Admin accounts (all idempotent — no-op once seeded) on every
# deploy before serving traffic. api is the single designated
# migration/seed runner (worker/rewrite don't also run it, to avoid
# concurrent-migration races) — nobody needs standing access to the
# Railway Postgres (it's only reachable from the private network
# anyway) to keep the schema and reference data current.
# Railway injects $PORT at runtime; default 8000 for local `docker run`.
CMD ["sh", "-c", "alembic upgrade head && python scripts/seed_sources.py && python scripts/seed_rewriter.py && python scripts/seed_admin.py && uvicorn api_app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
