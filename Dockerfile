# Production Dockerfile for Agentic RAG

FROM python:3.10-slim

WORKDIR /app

# System dependencies (gcc for native wheels that lack prebuilt binaries)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first so code changes don't bust this layer
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (secrets/data excluded via .dockerignore)
COPY . /app

# Run as non-root; /data holds the Chroma volume mount
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data/chroma_db /app/data \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
