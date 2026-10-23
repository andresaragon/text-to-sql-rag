ALTER SESSION SET CONTAINER = FREEPDB1;

INSERT INTO sales.customers (full_name, email, country) VALUES ('Ana Torres', 'ana.torres@example.com', 'Colombia');
INSERT INTO sales.customers (full_name, email, country) VALUES ('Marco Rossi', 'marco.rossi@example.com', 'Italy');
INSERT INTO sales.customers (full_name, email, country) VALUES ('Luisa Fernandez', 'luisa.fernandez@example.com', 'Mexico');

INSERT INTO sales.invoices (customer_id, amount, issued_date, due_date, status) VALUES (1, 1200.00, DATE '2026-06-01', DATE '2026-07-01', 'overdue');
INSERT INTO sales.invoices (customer_id, amount, issued_date, due_date, status) VALUES (1, 800.00, DATE '2026-07-15', DATE '2026-08-15', 'paid');
INSERT INTO sales.invoices (customer_id, amount, issued_date, due_date, status) VALUES (2, 3500.00, DATE '2026-08-01', DATE '2026-09-01', 'pending');
INSERT INTO sales.invoices (customer_id, amount, issued_date, due_date, status) VALUES (3, 950.00, DATE '2026-05-10', DATE '2026-06-10', 'overdue');

INSERT INTO sales.payments (invoice_id, amount_paid, paid_at, payment_method) VALUES (2, 800.00, TIMESTAMP '2026-08-10 10:15:00', 'bank_transfer');

INSERT INTO sales.collection_actions (invoice_id, action_type, action_date, notes) VALUES (1, 'email_reminder', DATE '2026-07-05', 'Primer recordatorio automático enviado.');
INSERT INTO sales.collection_actions (invoice_id, action_type, action_date, notes) VALUES (1, 'call', DATE '2026-07-20', 'Cliente solicitó plan de pago a 30 días.');
INSERT INTO sales.collection_actions (invoice_id, action_type, action_date, notes) VALUES (4, 'email_reminder', DATE '2026-06-15', 'Recordatorio automático enviado.');

COMMIT;
