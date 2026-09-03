# Descripción del esquema (fuente para embeddings del RAG)

Cada bloque de aquí se indexa como un documento independiente en
`schema_embeddings`. Esto es lo que el sistema recupera antes de pedirle
al LLM que genere SQL.

## Tabla: customers
Almacena los clientes. Columnas: customer_id (PK), full_name, email,
country, created_at. Cada factura (invoice) pertenece a un customer_id.

## Tabla: invoices
Almacena las facturas emitidas a los clientes. Columnas: invoice_id (PK),
customer_id (FK a customers), amount, currency, issued_date, due_date,
status. El campo status puede ser 'pending', 'paid' u 'overdue'.
Una factura está vencida (overdue) cuando su due_date ya pasó y no ha
sido pagada por completo.

## Tabla: payments
Almacena los pagos realizados contra una factura. Columnas: payment_id
(PK), invoice_id (FK a invoices), amount_paid, paid_at, payment_method.
Una factura puede tener uno o varios pagos parciales.

## Tabla: collection_actions
Registra las acciones de cobranza realizadas sobre una factura (llamadas,
recordatorios por email, negociaciones). Columnas: action_id (PK),
invoice_id (FK a invoices), action_type, action_date, notes.

## Ejemplo de pregunta → SQL (usado como ejemplo few-shot en el RAG)

Pregunta: "¿Cuántos clientes tienen facturas vencidas hace más de 30 días?"
SQL:
```sql
SELECT COUNT(DISTINCT customer_id)
FROM invoices
WHERE status = 'overdue'
  AND due_date < NOW() - INTERVAL '30 days';
```

Pregunta: "¿Cuál es el monto total pagado por cada cliente?"
SQL:
```sql
SELECT c.full_name, SUM(p.amount_paid) AS total_paid
FROM customers c
JOIN invoices i ON i.customer_id = c.customer_id
JOIN payments p ON p.invoice_id = i.invoice_id
GROUP BY c.full_name;
```
