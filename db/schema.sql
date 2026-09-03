-- Esquema de práctica: Facturación y Cobranza
-- Dominio elegido por similitud con experiencia profesional real
-- (automatización de pagos y negociación de deuda), sin usar datos reales.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE customers (
    customer_id     SERIAL PRIMARY KEY,
    full_name       VARCHAR(150) NOT NULL,
    email           VARCHAR(150) UNIQUE NOT NULL,
    country         VARCHAR(50),
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE invoices (
    invoice_id      SERIAL PRIMARY KEY,
    customer_id     INTEGER NOT NULL REFERENCES customers(customer_id),
    amount          NUMERIC(12, 2) NOT NULL,
    currency        VARCHAR(3) DEFAULT 'USD',
    issued_date     DATE NOT NULL,
    due_date        DATE NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending, paid, overdue
    CHECK (status IN ('pending', 'paid', 'overdue'))
);

CREATE TABLE payments (
    payment_id      SERIAL PRIMARY KEY,
    invoice_id      INTEGER NOT NULL REFERENCES invoices(invoice_id),
    amount_paid     NUMERIC(12, 2) NOT NULL,
    paid_at         TIMESTAMP NOT NULL,
    payment_method  VARCHAR(30) -- ej. bank_transfer, credit_card
);

CREATE TABLE collection_actions (
    action_id       SERIAL PRIMARY KEY,
    invoice_id      INTEGER NOT NULL REFERENCES invoices(invoice_id),
    action_type     VARCHAR(30) NOT NULL, -- ej. email_reminder, call, negotiation
    action_date     DATE NOT NULL,
    notes           TEXT
);

-- Tabla para almacenar los embeddings del esquema (RAG)
CREATE TABLE schema_embeddings (
    id              SERIAL PRIMARY KEY,
    object_name     VARCHAR(100) NOT NULL,   -- ej. 'invoices' o 'invoices.status'
    object_type     VARCHAR(20) NOT NULL,    -- 'table' | 'column' | 'example_query'
    description     TEXT NOT NULL,
    embedding       vector(384)              -- dimensión de all-MiniLM-L6-v2
);
