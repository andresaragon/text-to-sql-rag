#!/usr/bin/env bash
# Demo para grabar el GIF: espera a la API, hace una pregunta legítima, una fuera
# de dominio (debe dar 422) y muestra el cortafuegos SQL. Requiere `docker compose up`.
set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000}"
DEMO_PAUSE="${DEMO_PAUSE:-2}"
LEGIT_QUESTION="How many customers have overdue invoices?"
OUT_OF_DOMAIN_QUESTION="What is the capital of France?"

title() {
  echo
  echo "=== $1 ==="
  echo
}

ask() {
  # $1 = pregunta; imprime el cuerpo de la respuesta
  curl -sS --max-time 180 -X POST "$API_URL/query" \
    -H "Content-Type: application/json" \
    -d "{\"question\": \"$1\"}"
}

title "Waiting for the API"
for _ in $(seq 1 60); do
  if curl -fsS --max-time 2 "$API_URL/health" >/dev/null 2>&1; then
    echo "API ready at $API_URL"
    break
  fi
  sleep 1
done
curl -fsS --max-time 2 "$API_URL/health" >/dev/null || {
  echo "The API did not respond at $API_URL/health within 60 s" >&2
  exit 1
}
sleep "$DEMO_PAUSE"

title "Warming up the model..."
# La primera pregunta carga el modelo en Ollama (~40 s); la salida se descarta.
WARM_CODE=$(curl -sS --max-time 180 -o /dev/null -w '%{http_code}' -X POST "$API_URL/query" \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"$LEGIT_QUESTION\"}")
if [ "$WARM_CODE" != "200" ]; then
  echo "The warm-up question returned HTTP $WARM_CODE. Is Ollama reachable? See 'Ollama from Docker' in the README." >&2
  exit 1
fi
echo "Model is warm."
sleep "$DEMO_PAUSE"

title "Step 1: legitimate question"
echo "Question: $LEGIT_QUESTION"
echo
ask "$LEGIT_QUESTION" | python3 -m json.tool
sleep "$DEMO_PAUSE"

title "Step 2: out-of-domain question (expect HTTP 422)"
echo "Question: $OUT_OF_DOMAIN_QUESTION"
echo
HTTP_CODE=$(curl -sS --max-time 180 -o /dev/null -w '%{http_code}' -X POST "$API_URL/query" \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"$OUT_OF_DOMAIN_QUESTION\"}")
echo "HTTP status: $HTTP_CODE"
if [ "$HTTP_CODE" != "422" ]; then
  echo "Expected HTTP 422, got $HTTP_CODE" >&2
  exit 1
fi
sleep "$DEMO_PAUSE"

title "Step 3: SQL firewall"
docker compose exec -T api python -m scripts.demo_firewall

title "Demo finished"
