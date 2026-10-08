-- Esquema sintético ampliado para evaluar retrieval en un dominio comercial.
--
-- Está pensado para cargarse en una base de datos de prueba separada de la
-- demo mínima (`schema.sql`): contiene 20 tablas y una red de FKs con rutas
-- largas, tablas de detalle y entidades de nombres parecidos.

CREATE TABLE regions (
    region_id       SERIAL PRIMARY KEY,
    region_name     VARCHAR(100) NOT NULL UNIQUE,
    country         VARCHAR(50) NOT NULL
);

CREATE TABLE sales_representatives (
    sales_rep_id    SERIAL PRIMARY KEY,
    region_id       INTEGER NOT NULL REFERENCES regions(region_id),
    full_name       VARCHAR(150) NOT NULL,
    email           VARCHAR(150) NOT NULL UNIQUE,
    hired_at        DATE NOT NULL
);

CREATE TABLE customer_segments (
    segment_id      SERIAL PRIMARY KEY,
    segment_name    VARCHAR(100) NOT NULL UNIQUE,
    credit_limit    NUMERIC(12, 2) NOT NULL
);

CREATE TABLE customers (
    customer_id     SERIAL PRIMARY KEY,
    segment_id      INTEGER NOT NULL REFERENCES customer_segments(segment_id),
    sales_rep_id    INTEGER REFERENCES sales_representatives(sales_rep_id),
    full_name       VARCHAR(150) NOT NULL,
    email           VARCHAR(150) NOT NULL UNIQUE,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE customer_addresses (
    address_id      SERIAL PRIMARY KEY,
    customer_id     INTEGER NOT NULL REFERENCES customers(customer_id),
    address_type    VARCHAR(20) NOT NULL CHECK (address_type IN ('billing', 'shipping')),
    street          VARCHAR(150) NOT NULL,
    city            VARCHAR(100) NOT NULL,
    country         VARCHAR(50) NOT NULL,
    is_default      BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE customer_contacts (
    contact_id      SERIAL PRIMARY KEY,
    customer_id     INTEGER NOT NULL REFERENCES customers(customer_id),
    full_name       VARCHAR(150) NOT NULL,
    role_name       VARCHAR(100),
    email           VARCHAR(150),
    phone           VARCHAR(50),
    is_primary      BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE product_categories (
    category_id         SERIAL PRIMARY KEY,
    parent_category_id  INTEGER REFERENCES product_categories(category_id),
    category_name       VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE products (
    product_id      SERIAL PRIMARY KEY,
    category_id     INTEGER NOT NULL REFERENCES product_categories(category_id),
    sku             VARCHAR(50) NOT NULL UNIQUE,
    product_name    VARCHAR(150) NOT NULL,
    unit_price      NUMERIC(12, 2) NOT NULL,
    active          BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE warehouses (
    warehouse_id    SERIAL PRIMARY KEY,
    region_id       INTEGER NOT NULL REFERENCES regions(region_id),
    warehouse_name  VARCHAR(100) NOT NULL,
    city            VARCHAR(100) NOT NULL
);

CREATE TABLE inventory (
    warehouse_id    INTEGER NOT NULL REFERENCES warehouses(warehouse_id),
    product_id      INTEGER NOT NULL REFERENCES products(product_id),
    quantity_on_hand INTEGER NOT NULL CHECK (quantity_on_hand >= 0),
    reorder_point   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (warehouse_id, product_id)
);

CREATE TABLE orders (
    order_id            SERIAL PRIMARY KEY,
    customer_id         INTEGER NOT NULL REFERENCES customers(customer_id),
    sales_rep_id        INTEGER REFERENCES sales_representatives(sales_rep_id),
    shipping_address_id INTEGER REFERENCES customer_addresses(address_id),
    ordered_at          TIMESTAMP NOT NULL,
    status              VARCHAR(20) NOT NULL CHECK (status IN ('draft', 'confirmed', 'shipped', 'cancelled'))
);

CREATE TABLE order_items (
    order_item_id   SERIAL PRIMARY KEY,
    order_id        INTEGER NOT NULL REFERENCES orders(order_id),
    product_id      INTEGER NOT NULL REFERENCES products(product_id),
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    unit_price      NUMERIC(12, 2) NOT NULL
);

CREATE TABLE shipments (
    shipment_id     SERIAL PRIMARY KEY,
    order_id        INTEGER NOT NULL REFERENCES orders(order_id),
    warehouse_id    INTEGER NOT NULL REFERENCES warehouses(warehouse_id),
    shipped_at      TIMESTAMP,
    delivered_at    TIMESTAMP,
    status          VARCHAR(20) NOT NULL CHECK (status IN ('pending', 'shipped', 'delivered'))
);

CREATE TABLE shipment_items (
    shipment_item_id    SERIAL PRIMARY KEY,
    shipment_id         INTEGER NOT NULL REFERENCES shipments(shipment_id),
    order_item_id       INTEGER NOT NULL REFERENCES order_items(order_item_id),
    quantity_shipped    INTEGER NOT NULL CHECK (quantity_shipped > 0)
);

CREATE TABLE invoices (
    invoice_id      SERIAL PRIMARY KEY,
    order_id        INTEGER NOT NULL REFERENCES orders(order_id),
    customer_id     INTEGER NOT NULL REFERENCES customers(customer_id),
    issued_date     DATE NOT NULL,
    due_date        DATE NOT NULL,
    status          VARCHAR(20) NOT NULL CHECK (status IN ('pending', 'paid', 'overdue', 'cancelled')),
    total_amount    NUMERIC(12, 2) NOT NULL
);

CREATE TABLE invoice_items (
    invoice_item_id SERIAL PRIMARY KEY,
    invoice_id      INTEGER NOT NULL REFERENCES invoices(invoice_id),
    order_item_id   INTEGER NOT NULL REFERENCES order_items(order_item_id),
    product_id      INTEGER NOT NULL REFERENCES products(product_id),
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    line_amount     NUMERIC(12, 2) NOT NULL
);

CREATE TABLE payment_methods (
    payment_method_id   SERIAL PRIMARY KEY,
    method_name         VARCHAR(50) NOT NULL UNIQUE,
    provider_name       VARCHAR(100)
);

CREATE TABLE payments (
    payment_id          SERIAL PRIMARY KEY,
    invoice_id          INTEGER NOT NULL REFERENCES invoices(invoice_id),
    payment_method_id   INTEGER NOT NULL REFERENCES payment_methods(payment_method_id),
    amount_paid         NUMERIC(12, 2) NOT NULL CHECK (amount_paid > 0),
    paid_at             TIMESTAMP NOT NULL,
    payment_reference   VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE collection_actions (
    action_id       SERIAL PRIMARY KEY,
    invoice_id      INTEGER NOT NULL REFERENCES invoices(invoice_id),
    action_type     VARCHAR(30) NOT NULL CHECK (action_type IN ('email_reminder', 'call', 'negotiation')),
    action_date     DATE NOT NULL,
    notes           TEXT
);

CREATE TABLE credit_notes (
    credit_note_id  SERIAL PRIMARY KEY,
    invoice_id      INTEGER NOT NULL REFERENCES invoices(invoice_id),
    issued_date     DATE NOT NULL,
    amount          NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    reason          VARCHAR(200) NOT NULL
);
