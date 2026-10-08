"""
Load test para POST /query (Locust).

Objetivo: medir el rendimiento ACTUAL del endpoint bajo carga concurrente,
antes de tocar nada de escalamiento (caching, connection pooling, etc.).
Este script es puramente instrumentación externa — no importa ni modifica
código de app/core, app/api ni app/config.

Uso (con el server ya levantado con `uvicorn app.main:app`):

    locust -f scripts/load_test.py --headless -u 10 -r 2 -t 2m \
        --host http://localhost:8000 --csv=results

Esto genera results_stats.csv (throughput, latencias por endpoint),
results_stats_history.csv y results_failures.csv.

--- Nota sobre latencia por etapa (retrieval / Ollama / DB) ---

El pipeline de /query hace 4 etapas en un solo request HTTP (ver
app/api/routes.py): retrieval pgvector -> generate_sql vía Ollama ->
validate_and_prepare (AST) -> execute_select. Locust solo puede medir
la latencia total del request desde afuera; separar por etapa
requeriría instrumentar app/core/sql_generator.py y app/core/retrieval.py
para loguear timestamps internos (por ejemplo, en response headers o en
logs del server), lo cual está fuera de alcance de este script según las
restricciones de la tarea (no tocar app/core/*).

Como proxy indirecto, este script también golpea GET /health (un
endpoint sin RAG, sin LLM y sin DB) con baja frecuencia, bajo el nombre
"health_baseline" en el reporte. La diferencia entre la latencia de
health_baseline y la de /query es, aproximadamente, el costo combinado
de retrieval + generación SQL + validación + ejecución — y dado que
Ollama corre inferencia local (probablemente CPU-bound), es el
sospechoso más probable de dominar esa diferencia. Si se quiere una
descomposición exacta por etapa, el siguiente paso sería agregar timing
interno a sql_generator.py y retrieval.py (fuera de alcance aquí).
"""

import random

from locust import HttpUser, task, between

# Preguntas representativas del dominio documentado en
# data/schema_docs/tables.md (facturas, clientes, pagos, cobranza).
# Se evitan preguntas genéricas: todas usan vocabulario y relaciones
# reales del esquema (customers, invoices, payments, collection_actions).
QUESTIONS = [
    "¿Cuántos clientes tienen facturas vencidas hace más de 30 días?",
    "¿Cuál es el monto total pagado por cada cliente?",
    "¿Qué facturas están pendientes de pago actualmente?",
    "¿Cuáles son los clientes con mayor monto de facturas vencidas?",
    "¿Qué acciones de cobranza se han hecho sobre facturas vencidas?",
    "¿Cuántos pagos parciales se registraron el último mes?",
    "¿Cuál es el promedio de días entre la emisión y el pago de una factura?",
    "¿Qué clientes no han hecho ningún pago todavía?",
    "¿Cuántas facturas se emitieron por mes en el último año?",
    "¿Cuál es el método de pago más utilizado por los clientes?",
]


class TextToSqlUser(HttpUser):
    """Usuario simulado golpeando POST /query con preguntas variadas."""

    host = "http://localhost:8000"
    wait_time = between(1, 3)

    @task(9)
    def ask_question(self):
        question = random.choice(QUESTIONS)
        # Los 400 (UnsafeQueryError, SQL rechazado por safety.py) cuentan
        # como error en el reporte de Locust a propósito: son parte de la
        # tasa de error real que interesa medir, no un crash del server.
        self.client.post("/query", json={"question": question}, name="/query")

    @task(1)
    def health_baseline(self):
        self.client.get("/health", name="health_baseline")
