#!/bin/bash
# Production deployment script (single-host).
# CI is responsible for tests; set RUN_TESTS=true to run them here anyway.

set -euo pipefail

echo "Starting Agentic RAG production deployment..."

ENV_FILE="${ENV_FILE:-.env.production}"
RUN_TESTS="${RUN_TESTS:-false}"
RUN_EVAL="${RUN_EVAL:-false}"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found — copy .env.production.example and configure secrets"
    exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [ "${ENVIRONMENT:-development}" = "production" ]; then
    if [ -z "${OPENAI_API_KEY:-}" ]; then
        echo "ERROR: OPENAI_API_KEY is required"
        exit 1
    fi
    if [ -z "${API_KEY:-}" ]; then
        echo "ERROR: API_KEY is required — authentication is mandatory in production"
        exit 1
    fi
fi

echo "Installing pinned dependencies..."
pip install --quiet -r requirements.txt

CHROMA_DIR="${CHROMA_PERSIST_DIR:-./data/chroma_db}"
if [ ! -d "$CHROMA_DIR" ] || [ -z "$(ls -A "$CHROMA_DIR" 2>/dev/null)" ]; then
    echo "Vector store empty — ingesting documents..."
    python -m src.ingestion.ingest --source data/sample_docs
fi

if [ "$RUN_TESTS" = "true" ]; then
    echo "Running test suite..."
    pytest tests/ -q
fi

if [ "$RUN_EVAL" = "true" ]; then
    echo "Running evaluation suite..."
    python -m src.evaluation.evaluate_all_modes
fi

echo "Starting API server on port 8000..."
exec uvicorn src.api.server:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "${API_WORKERS:-1}" \
    --log-level info
