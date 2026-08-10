#!/bin/bash
# Production deployment script (single-host, no container runtime).
#
# For a real deployment prefer `docker compose up -d --build`, which also brings
# up Redis, Chroma, and the frontend with hardened defaults. This script exists
# for a bare-metal host or a quick staging box.
#
# Secrets: reading .env.production off disk is the fallback path. If you have a
# secret manager, export the variables from it and point ENV_FILE at a file that
# holds only non-secret config.
#
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

# Refuse a world-readable secrets file: everything below is about to be loaded
# into the process environment.
perms="$(stat -f '%Lp' "$ENV_FILE" 2>/dev/null || stat -c '%a' "$ENV_FILE")"
if [ "$(( 8#$perms & 8#077 ))" -ne 0 ]; then
    echo "ERROR: $ENV_FILE is group/world readable (mode $perms)"
    echo "       Fix with: chmod 600 $ENV_FILE"
    exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

fail() { echo "ERROR: $1"; exit 1; }

if [ "${ENVIRONMENT:-development}" = "production" ]; then
    [ -n "${OPENAI_API_KEY:-}" ] || fail "OPENAI_API_KEY is required"
    [ -n "${API_KEY:-}" ] || fail "API_KEY is required — authentication is mandatory in production"
    [ "${#API_KEY}" -ge 32 ] || fail "API_KEY must be at least 32 characters (openssl rand -hex 32)"
    [ "${CORS_ORIGINS:-*}" != "*" ] || fail "CORS_ORIGINS='*' is not allowed in production"

    # Budgets live in-process unless Redis backs them; multiple workers would
    # silently multiply every configured ceiling. The app refuses to start on
    # this combination too — catching it here gives a clearer message sooner.
    workers="${API_WORKERS:-1}"
    if [ "$workers" -gt 1 ] && [ "${RATE_LIMIT_BACKEND:-auto}" = "memory" ]; then
        fail "API_WORKERS=$workers requires RATE_LIMIT_BACKEND=redis (per-worker budgets otherwise)"
    fi
fi

echo "Installing pinned dependencies..."
pip install --quiet -r requirements.txt

CHROMA_DIR="${CHROMA_PERSIST_DIR:-./data/chroma_db}"
if [ "${CHROMA_MODE:-persistent}" = "persistent" ] &&
   { [ ! -d "$CHROMA_DIR" ] || [ -z "$(ls -A "$CHROMA_DIR" 2>/dev/null)" ]; }; then
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
