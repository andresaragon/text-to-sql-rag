-- Datos de ejemplo para desarrollo y pruebas locales

INSERT INTO customers (full_name, email, country) VALUES
('Ana Torres', 'ana.torres@example.com', 'Colombia'),
('Marco Rossi', 'marco.rossi@example.com', 'Italy'),
('Luisa Fernandez', 'luisa.fernandez@example.com', 'Mexico');

INSERT INTO invoices (customer_id, amount, issued_date, due_date, status) VALUES
(1, 1200.00, '2026-06-01', '2026-07-01', 'overdue'),
(1, 800.00,  '2026-07-15', '2026-08-15', 'paid'),
(2, 3500.00, '2026-08-01', '2026-09-01', 'pending'),
(3, 950.00,  '2026-05-10', '2026-06-10', 'overdue');

INSERT INTO payments (invoice_id, amount_paid, paid_at, payment_method) VALUES
(2, 800.00, '2026-08-10 10:15:00', 'bank_transfer');

INSERT INTO collection_actions (invoice_id, action_type, action_date, notes) VALUES
(1, 'email_reminder', '2026-07-05', 'Primer recordatorio automático enviado.'),
(1, 'call', '2026-07-20', 'Cliente solicitó plan de pago a 30 días.'),
(4, 'email_reminder', '2026-06-15', 'Recordatorio automático enviado.');
