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
COPY scripts /app/scripts
COPY services/worker /app/services/worker

# torch resolves to the CPU-only build here (root pyproject.toml pins it
# to download.pytorch.org/whl/cpu via [tool.uv.sources]) — Railway
# containers have no GPU, and the default PyPI `torch` wheel for Linux
# drags in the full CUDA stack (~3GB+) for nothing.
RUN uv sync --frozen --package unum-worker
ENV PATH="/app/.venv/bin:$PATH"

RUN PYTHON_BIN=/app/.venv/bin/python bash scripts/gen_proto.sh

# Bakes the multilingual embedding model into the image so containers
# don't depend on reaching HuggingFace Hub at runtime (and don't pay a
# ~1min download on every cold start).
RUN python -c "from worker_app.dedup.embeddings import _model; _model()"

ENV PYTHONUNBUFFERED=1
EXPOSE 8001

CMD ["sh", "-c", "uvicorn worker_app.main:app --host 0.0.0.0 --port ${PORT:-8001}"]
