# Production image for Agentic RAG.
#
# Multi-stage: wheels are compiled in the builder, so the compiler toolchain
# never ships in the runtime image.

# --- Builder -----------------------------------------------------------------
FROM python:3.14-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
# Build every dependency to a wheel so the runtime stage installs without gcc.
RUN pip wheel --wheel-dir /wheels -r requirements.txt

# --- Runtime -----------------------------------------------------------------
FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# Create the user before copying so application code is owned by root and is
# not writable by the process that runs it.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data/chroma_db /app/data /app/data/sources \
    && chown -R appuser:appuser /data /app/data

# Application code (secrets/data excluded via .dockerignore)
COPY --chown=root:root . /app

USER appuser

EXPOSE 8000

# Liveness only — /health/ready is auth-gated and checks dependencies.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=5).status == 200 else 1)"

CMD ["uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
