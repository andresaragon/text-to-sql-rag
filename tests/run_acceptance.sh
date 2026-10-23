#!/usr/bin/env bash
# Aceptación completa de SPEC.md: unidad y estática sin Docker; luego integración contra un Oracle
# real que esta misma ejecución levanta (y baja al terminar) con el override de compose.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-python3}"
export DATABASE_URL="${DATABASE_URL:-postgresql://x:x@127.0.0.1:9/x}"
export OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:9}"
export WARMUP_ON_STARTUP=false
PROJECT="tsr-accept-$$"
COMPOSE=(docker compose -p "$PROJECT" -f docker-compose.yml -f docker-compose.oracle.yml)
cleanup() { "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "== 1/2 unidad y estática (sin Docker)"
"$PY" -m pytest -q -p no:cacheprovider --ignore=tests/integration

echo "== 2/2 integración contra Oracle real"
"${COMPOSE[@]}" up -d --wait --wait-timeout 300 oracle
ORACLE_INTEGRATION=1 "$PY" -m pytest -q -p no:cacheprovider tests/integration
