"""
Tests para app/core/safety.py — la parte más crítica del proyecto.

Estos casos deben pasar cuando implementes is_safe_select():
"""

import pytest

from app.core.safety import (
    enforce_limit,
    is_safe_select,
    UnsafeQueryError,
    validate_and_prepare,
)


def test_valid_select_is_safe():
    sql = "SELECT * FROM invoices WHERE status = 'overdue';"
    assert is_safe_select(sql) is True


def test_drop_table_is_rejected():
    sql = "DROP TABLE invoices;"
    assert is_safe_select(sql) is False


def test_delete_is_rejected():
    sql = "DELETE FROM invoices WHERE invoice_id = 1;"
    assert is_safe_select(sql) is False


def test_select_with_subquery_insert_is_rejected():
    """Caso trampa: un SELECT que esconde un INSERT vía statement múltiple."""
    sql = "SELECT * FROM invoices; INSERT INTO invoices (amount) VALUES (999);"
    assert is_safe_select(sql) is False


def test_update_disguised_as_comment_is_rejected():
    sql = "SELECT * FROM invoices; -- ok\nUPDATE invoices SET amount = 0;"
    assert is_safe_select(sql) is False


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
