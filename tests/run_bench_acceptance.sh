#!/usr/bin/env bash
# Aceptación del benchmark A/B: unidad y estática sin Docker; luego pruebas contra Postgres y Oracle
# reales que esta misma ejecución levanta (y baja) con compose y llena con el dataset sintético.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-python3}"
export OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:9}"
export WARMUP_ON_STARTUP=false
PROJECT="tsr-bench-$$"
COMPOSE=(docker compose -p "$PROJECT" -f docker-compose.yml -f docker-compose.oracle.yml)
cleanup() { "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "== 1/2 unidad y estática (sin Docker)"
DATABASE_URL="${DATABASE_URL:-postgresql://x:x@127.0.0.1:9/x}" "$PY" -m pytest -q -p no:cacheprovider \
  --ignore=tests/integration --ignore=tests/integration_bench

echo "== 2/2 Postgres y Oracle reales con el dataset completo"
"${COMPOSE[@]}" up -d --wait --wait-timeout 300 db oracle
DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/postgres" BENCH_LIVE=1 \
  "$PY" -m pytest -q -p no:cacheprovider tests/integration_bench
