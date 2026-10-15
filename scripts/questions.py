"""Preguntas de dominio compartidas por scripts/load_test.py y scripts/bench_query.py."""

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
