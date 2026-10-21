# Descripción del esquema (fuente para embeddings del RAG)

Cada bloque de aquí se indexa como un documento independiente en
`schema_embeddings`. Esto es lo que el sistema recupera antes de pedirle
al LLM que genere SQL.

## Tabla: customers
Almacena los clientes, compradores o personas titulares de cuentas (ejemplos: Ana Torres, Marco Rossi, Luisa Fernandez).
Columnas:
- customer_id (PK): Identificador único del cliente.
- full_name: Nombre y apellido del cliente (permite filtrar por personas específicas, ej: full_name = 'Ana Torres').
- email: Dirección de correo electrónico del cliente.
- country: País de residencia o facturación (ej: Colombia, Italy, Mexico).
- created_at: Fecha y hora de registro del cliente.
Relaciones y consultas:
Cada factura en invoices pertenece a un customer_id. Para saber cuánto debe un cliente, qué facturas tiene o qué pagos ha hecho, se debe enlazar customers con invoices mediante: invoices.customer_id = customers.customer_id.

## Tabla: invoices
Almacena las facturas emitidas, cobros, deudas y saldos por cobrar a los clientes.
Columnas:
- invoice_id (PK): Identificador único de la factura.
- customer_id (FK a customers): Cliente al que se le emitió la factura.
- amount: Monto total facturado.
- currency: Moneda de facturación (ej: USD).
- issued_date: Fecha de emisión de la factura.
- due_date: Fecha límite de vencimiento para el pago.
- status: Estado actual de la factura. Tres valores posibles:
  * 'pending': Factura pendiente de pago emitida pero aún no saldada.
  * 'overdue': Factura vencida y en mora (su due_date ya pasó y no ha sido pagada por completo).
  * 'paid': Factura pagada y liquidada totalmente.
Reglas de negocio:
- ¿Cuánto debe un cliente o cuál es su deuda pendiente?: Corresponde a la suma del monto (amount) de sus facturas que no están pagadas (status IN ('pending', 'overdue') o status = 'pending') menos los abonos recibidos.
- Facturas pendientes de pago: Se consultan filtrando status = 'pending'.
- Facturas vencidas: Se consultan filtrando status = 'overdue'.
- Agrupación por meses: Para agrupar o contar facturas por mes se utiliza DATE_TRUNC('month', issued_date).

## Tabla: payments
Almacena los pagos, abonos y transacciones realizadas contra una factura.
Columnas:
- payment_id (PK): Identificador único del pago.
- invoice_id (FK a invoices): Factura a la que se aplica el pago.
- amount_paid: Monto abonado o pagado en la transacción.
- paid_at: Fecha y hora exacta en que se realizó el pago.
- payment_method: Método o canal de pago utilizado (ejemplos: 'bank_transfer', 'credit_card'). NO indica si el pago es parcial o total.
Reglas de negocio y relaciones:
- Clave de relación con clientes: La tabla payments NO tiene columna customer_id. Para relacionar pagos con clientes, SIEMPRE se debe hacer JOIN con invoices: customers c JOIN invoices i ON i.customer_id = c.customer_id JOIN payments p ON p.invoice_id = i.invoice_id.
- Pagos parciales y abonos: Cada registro en payments representa un abono o pago (sea parcial o total). Para contar pagos o abonos en un periodo: COUNT(*) FROM payments WHERE paid_at >= fecha_limite.
- Promedio de días entre emisión y pago: Se calcula con AVG(p.paid_at::date - i.issued_date) uniendo payments con invoices por invoice_id.
- Clientes sin pagos: Clientes cuyo customer_id no existe en invoices con pagos registrados (c.customer_id NOT IN (SELECT i.customer_id FROM invoices i JOIN payments p ON p.invoice_id = i.invoice_id)).

## Tabla: collection_actions
Registra las gestiones y acciones de cobranza realizadas sobre facturas en mora o vencidas (llamadas telefónicas, recordatorios por email, cartas y acuerdos de negociación).
Columnas:
- action_id (PK): Identificador único de la acción de cobro.
- invoice_id (FK a invoices): Factura sobre la que se gestionó la cobranza.
- action_type: Tipo de gestión (ejemplos: 'email_reminder', 'call', 'negotiation').
- action_date: Fecha en que se ejecutó la acción de cobranza.
- notes: Observaciones y notas detalladas del contacto con el deudor.
Reglas de negocio:
Para consultar acciones de cobranza sobre facturas vencidas: collection_actions ca JOIN invoices i ON i.invoice_id = ca.invoice_id WHERE i.status = 'overdue'.

## Ejemplo de pregunta → SQL (usado como ejemplo few-shot en el RAG)

Pregunta: "¿Cuál es el monto total pagado por cada cliente?"
SQL:
```sql
SELECT c.full_name, COALESCE(SUM(p.amount_paid), 0) AS total_paid
FROM customers c
JOIN invoices i ON i.customer_id = c.customer_id
JOIN payments p ON p.invoice_id = i.invoice_id
GROUP BY c.full_name;
```

Pregunta: "¿Cuánto debe el cliente Ana Torres en facturas vencidas?"
SQL:
```sql
SELECT c.full_name, SUM(i.amount) AS total_debt
FROM customers c
JOIN invoices i ON i.customer_id = c.customer_id
WHERE c.full_name = 'Ana Torres'
  AND i.status = 'overdue'
GROUP BY c.full_name;
```

Pregunta: "¿Qué facturas están pendientes de pago actualmente?"
SQL:
```sql
SELECT invoice_id, customer_id, amount, issued_date, due_date
FROM invoices
WHERE status = 'pending';
```

Pregunta: "¿Cuántas facturas se emitieron por mes en el último año?"
SQL:
```sql
SELECT DATE_TRUNC('month', issued_date) AS mes, COUNT(*) AS total_facturas
FROM invoices
WHERE issued_date >= CURRENT_DATE - INTERVAL '1 year'
GROUP BY DATE_TRUNC('month', issued_date)
ORDER BY mes;
```
