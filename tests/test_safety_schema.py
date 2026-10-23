"""La lista blanca de tablas también debe controlar el ESQUEMA (y el catálogo).

Antes solo se comparaba el nombre de la tabla: `SELECT * FROM otro.customers` pasaba
porque `customers` está en la lista blanca, aunque viva en un esquema no autorizado.
Escritas antes de implementar (rojas por diseño); no se editan para hacerlas pasar.
"""

import pytest

from app.config import settings
from app.core.safety import TableNotAllowedError, validate_and_prepare

REJECT_SCHEMA = [
    "SELECT * FROM otro.customers",
    "SELECT * FROM OTRO.CUSTOMERS",
    'SELECT * FROM "otro"."customers"',
    "SELECT * FROM pg_catalog.customers",
    "SELECT * FROM postgres.public.customers",
    "SELECT * FROM public.otro.customers",
    "SELECT * FROM public.customers c JOIN otro.invoices i ON i.customer_id = c.customer_id",
    "SELECT * FROM customers WHERE customer_id IN (SELECT customer_id FROM otro.invoices)",
    "WITH x AS (SELECT * FROM otro.customers) SELECT * FROM x",
    "SELECT * FROM customers UNION SELECT * FROM otro.customers",
    "SELECT (SELECT COUNT(*) FROM otro.payments) FROM customers",
    # Una CTE con el mismo nombre NO puede ocultar una tabla calificada de otro esquema.
    "WITH customers AS (SELECT 1 AS customer_id) SELECT * FROM otro.customers",
    "WITH invoices AS (SELECT 1) SELECT * FROM invoices, otro.invoices",
]

ACCEPT_SCHEMA = [
    "SELECT * FROM public.customers",
    "SELECT * FROM PUBLIC.CUSTOMERS",
    'SELECT * FROM "public"."customers"',
    "SELECT * FROM customers",
    "SELECT c.* FROM public.customers c JOIN invoices i ON i.customer_id = c.customer_id",
    "WITH x AS (SELECT * FROM public.customers) SELECT * FROM x",
    "WITH customers AS (SELECT 1 AS customer_id) SELECT * FROM customers",
]


@pytest.mark.parametrize("sql", REJECT_SCHEMA)
def test_reject_tables_outside_the_allowed_schema(sql):
    with pytest.raises(TableNotAllowedError):
        validate_and_prepare(sql, max_rows=100)


@pytest.mark.parametrize("sql", ACCEPT_SCHEMA)
def test_accept_unqualified_and_allowed_schema_tables(sql):
    assert validate_and_prepare(sql, max_rows=100).upper().startswith(("SELECT", "WITH"))


def test_default_allowed_schema_is_public():
    assert settings.allowed_schema == "public"


@pytest.mark.parametrize(
    "sql", ["SELECT * FROM finance.customers", "SELECT * FROM FINANCE.customers", "SELECT * FROM customers"]
)
def test_custom_allowed_schema_via_argument(sql):
    assert validate_and_prepare(sql, max_rows=100, allowed_schema="finance")


@pytest.mark.parametrize("sql", ["SELECT * FROM public.customers", "SELECT * FROM otro.customers"])
def test_custom_allowed_schema_rejects_every_other_schema(sql):
    with pytest.raises(TableNotAllowedError):
        validate_and_prepare(sql, max_rows=100, allowed_schema="finance")


def test_allowed_schema_defaults_to_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "allowed_schema", "finance")
    assert validate_and_prepare("SELECT * FROM finance.customers", max_rows=100)
    with pytest.raises(TableNotAllowedError):
        validate_and_prepare("SELECT * FROM public.customers", max_rows=100)
