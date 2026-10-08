-- Datos deterministas para db/schema_large.sql. Cargar en una base vacía.

INSERT INTO regions (region_id, region_name, country) VALUES
    (1, 'Andina', 'Colombia'),
    (2, 'Centroamérica', 'Mexico'),
    (3, 'Europa Sur', 'Spain');

INSERT INTO sales_representatives (sales_rep_id, region_id, full_name, email, hired_at) VALUES
    (1, 1, 'Valentina Ruiz', 'valentina.ruiz@example.com', '2024-01-10'),
    (2, 2, 'Diego Morales', 'diego.morales@example.com', '2023-05-20'),
    (3, 3, 'Elena Martín', 'elena.martin@example.com', '2022-09-15');

INSERT INTO customer_segments (segment_id, segment_name, credit_limit) VALUES
    (1, 'Enterprise', 50000.00),
    (2, 'Mid-market', 15000.00),
    (3, 'SMB', 5000.00);

INSERT INTO customers (customer_id, segment_id, sales_rep_id, full_name, email, created_at) VALUES
    (1, 1, 1, 'Comercial Andina SAS', 'compras@andina.example.com', '2025-01-15 09:00:00'),
    (2, 2, 2, 'Distribuciones del Centro SA', 'ventas@centro.example.com', '2025-02-10 10:00:00'),
    (3, 3, 3, 'Tienda Sol SL', 'admin@tiendasol.example.com', '2025-03-05 11:00:00');

INSERT INTO customer_addresses (address_id, customer_id, address_type, street, city, country, is_default) VALUES
    (1, 1, 'billing', 'Calle 72 #10-34', 'Bogotá', 'Colombia', TRUE),
    (2, 1, 'shipping', 'Zona Industrial 5', 'Bogotá', 'Colombia', TRUE),
    (3, 2, 'billing', 'Av. Reforma 210', 'Ciudad de México', 'Mexico', TRUE),
    (4, 2, 'shipping', 'Parque Logístico Norte', 'Monterrey', 'Mexico', TRUE),
    (5, 3, 'billing', 'Calle Colón 18', 'Madrid', 'Spain', TRUE),
    (6, 3, 'shipping', 'Calle Colón 18', 'Madrid', 'Spain', TRUE);

INSERT INTO customer_contacts (contact_id, customer_id, full_name, role_name, email, phone, is_primary) VALUES
    (1, 1, 'Ana Gómez', 'Finance Manager', 'ana.gomez@andina.example.com', '+57-601-5550101', TRUE),
    (2, 1, 'Luis Pérez', 'Warehouse Lead', 'luis.perez@andina.example.com', '+57-601-5550102', FALSE),
    (3, 2, 'María López', 'Buyer', 'maria.lopez@centro.example.com', '+52-55-5550103', TRUE),
    (4, 3, 'Javier Soto', 'Owner', 'javier.soto@tiendasol.example.com', '+34-91-5550104', TRUE);

INSERT INTO product_categories (category_id, parent_category_id, category_name) VALUES
    (1, NULL, 'Tecnología'),
    (2, 1, 'Laptops'),
    (3, 1, 'Accesorios'),
    (4, NULL, 'Mobiliario');

INSERT INTO products (product_id, category_id, sku, product_name, unit_price, active) VALUES
    (1, 2, 'LAP-14-PRO', 'Laptop Pro 14', 1500.00, TRUE),
    (2, 2, 'LAP-13-AIR', 'Laptop Air 13', 950.00, TRUE),
    (3, 3, 'DOCK-USBC', 'Dock USB-C', 180.00, TRUE),
    (4, 4, 'DESK-ERG', 'Escritorio ergonómico', 420.00, TRUE),
    (5, 3, 'MOUSE-WLS', 'Mouse inalámbrico', 35.00, TRUE);

INSERT INTO warehouses (warehouse_id, region_id, warehouse_name, city) VALUES
    (1, 1, 'Bodega Bogotá', 'Bogotá'),
    (2, 2, 'Bodega Monterrey', 'Monterrey'),
    (3, 3, 'Bodega Madrid', 'Madrid');

INSERT INTO inventory (warehouse_id, product_id, quantity_on_hand, reorder_point) VALUES
    (1, 1, 2, 5), (1, 2, 20, 8), (1, 3, 40, 10), (1, 4, 6, 3), (1, 5, 100, 20),
    (2, 1, 10, 5), (2, 2, 3, 8), (2, 3, 15, 10), (2, 4, 8, 3), (2, 5, 50, 20),
    (3, 1, 5, 5), (3, 2, 12, 8), (3, 3, 25, 10), (3, 4, 2, 3), (3, 5, 60, 20);

INSERT INTO orders (order_id, customer_id, sales_rep_id, shipping_address_id, ordered_at, status) VALUES
    (1, 1, 1, 2, '2026-05-10 09:30:00', 'shipped'),
    (2, 2, 2, 4, '2026-06-15 14:00:00', 'shipped'),
    (3, 3, 3, 6, '2026-07-01 11:20:00', 'confirmed'),
    (4, 1, 1, 2, '2026-08-05 16:45:00', 'confirmed');

INSERT INTO order_items (order_item_id, order_id, product_id, quantity, unit_price) VALUES
    (1, 1, 1, 4, 1500.00), (2, 1, 3, 4, 180.00),
    (3, 2, 2, 10, 950.00), (4, 2, 5, 10, 35.00),
    (5, 3, 4, 3, 420.00), (6, 3, 5, 3, 35.00),
    (7, 4, 1, 2, 1500.00), (8, 4, 3, 2, 180.00);

INSERT INTO shipments (shipment_id, order_id, warehouse_id, shipped_at, delivered_at, status) VALUES
    (1, 1, 1, '2026-05-12 08:00:00', '2026-05-14 13:30:00', 'delivered'),
    (2, 2, 2, '2026-06-18 09:15:00', '2026-06-21 15:45:00', 'delivered'),
    (3, 4, 1, NULL, NULL, 'pending');

INSERT INTO shipment_items (shipment_item_id, shipment_id, order_item_id, quantity_shipped) VALUES
    (1, 1, 1, 4), (2, 1, 2, 4), (3, 2, 3, 10), (4, 2, 4, 10);

INSERT INTO invoices (invoice_id, order_id, customer_id, issued_date, due_date, status, total_amount) VALUES
    (1, 1, 1, '2026-05-10', '2026-06-09', 'overdue', 6720.00),
    (2, 2, 2, '2026-06-15', '2026-07-15', 'paid', 9850.00),
    (3, 3, 3, '2026-07-01', '2026-07-31', 'pending', 1365.00),
    (4, 4, 1, '2026-08-05', '2026-09-04', 'pending', 3360.00);

INSERT INTO invoice_items (invoice_item_id, invoice_id, order_item_id, product_id, quantity, line_amount) VALUES
    (1, 1, 1, 1, 4, 6000.00), (2, 1, 2, 3, 4, 720.00),
    (3, 2, 3, 2, 10, 9500.00), (4, 2, 4, 5, 10, 350.00),
    (5, 3, 5, 4, 3, 1260.00), (6, 3, 6, 5, 3, 105.00),
    (7, 4, 7, 1, 2, 3000.00), (8, 4, 8, 3, 2, 360.00);

INSERT INTO payment_methods (payment_method_id, method_name, provider_name) VALUES
    (1, 'bank_transfer', 'Banco de prueba'),
    (2, 'credit_card', 'Tarjeta de prueba');

INSERT INTO payments (payment_id, invoice_id, payment_method_id, amount_paid, paid_at, payment_reference) VALUES
    (1, 2, 1, 9850.00, '2026-06-30 10:20:00', 'TRX-2026-0001'),
    (2, 1, 2, 2000.00, '2026-07-15 16:10:00', 'TRX-2026-0002');

INSERT INTO collection_actions (action_id, invoice_id, action_type, action_date, notes) VALUES
    (1, 1, 'email_reminder', '2026-06-15', 'Primer recordatorio por saldo pendiente.'),
    (2, 1, 'call', '2026-07-01', 'Cliente solicitó negociación de pago.'),
    (3, 1, 'negotiation', '2026-07-10', 'Se acordó pago parcial con tarjeta.');

INSERT INTO credit_notes (credit_note_id, invoice_id, issued_date, amount, reason) VALUES
    (1, 2, '2026-06-20', 350.00, 'Descuento comercial posterior a la facturación.');

SELECT setval(pg_get_serial_sequence('regions', 'region_id'), 3, true);
SELECT setval(pg_get_serial_sequence('sales_representatives', 'sales_rep_id'), 3, true);
SELECT setval(pg_get_serial_sequence('customer_segments', 'segment_id'), 3, true);
SELECT setval(pg_get_serial_sequence('customers', 'customer_id'), 3, true);
SELECT setval(pg_get_serial_sequence('customer_addresses', 'address_id'), 6, true);
SELECT setval(pg_get_serial_sequence('customer_contacts', 'contact_id'), 4, true);
SELECT setval(pg_get_serial_sequence('product_categories', 'category_id'), 4, true);
SELECT setval(pg_get_serial_sequence('products', 'product_id'), 5, true);
SELECT setval(pg_get_serial_sequence('warehouses', 'warehouse_id'), 3, true);
SELECT setval(pg_get_serial_sequence('orders', 'order_id'), 4, true);
SELECT setval(pg_get_serial_sequence('order_items', 'order_item_id'), 8, true);
SELECT setval(pg_get_serial_sequence('shipments', 'shipment_id'), 3, true);
SELECT setval(pg_get_serial_sequence('shipment_items', 'shipment_item_id'), 4, true);
SELECT setval(pg_get_serial_sequence('invoices', 'invoice_id'), 4, true);
SELECT setval(pg_get_serial_sequence('invoice_items', 'invoice_item_id'), 8, true);
SELECT setval(pg_get_serial_sequence('payment_methods', 'payment_method_id'), 2, true);
SELECT setval(pg_get_serial_sequence('payments', 'payment_id'), 2, true);
SELECT setval(pg_get_serial_sequence('collection_actions', 'action_id'), 3, true);
SELECT setval(pg_get_serial_sequence('credit_notes', 'credit_note_id'), 1, true);
