import pytest

from app.core.safety import (
    NonSelectQueryError,
    UnsafeQueryError,
    validate_ast,
    validate_and_prepare,
)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * INTO newt FROM invoices",
        "WITH d AS (DELETE FROM invoices RETURNING *) SELECT * FROM d",
        "WITH d AS (INSERT INTO invoices VALUES (1) RETURNING *) SELECT * FROM d",
        "WITH d AS (UPDATE invoices SET x = 1 RETURNING *) SELECT * FROM d",
        "SELECT * FROM invoices FOR UPDATE",
        "SELECT * FROM invoices FOR SHARE",
        "SELECT * FROM (SELECT * FROM invoices FOR UPDATE) x",
        "WITH a AS (SELECT * FROM invoices FOR UPDATE) SELECT * FROM a",
        "SELECT * FROM invoices WHERE id IN (SELECT id FROM payments FOR SHARE)",
        "WITH a AS (SELECT * INTO x FROM invoices) SELECT * FROM a",
    ],
)
def test_unsafe_select_shapes_are_rejected(sql):
    with pytest.raises(UnsafeQueryError):
        validate_ast(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a FROM invoices",
        "WITH a AS (SELECT 1) SELECT * FROM a",
        "SELECT * FROM invoices WHERE x IN (SELECT y FROM payments)",
    ],
)
def test_read_only_select_shapes_are_accepted(sql):
    validate_ast(sql)


def test_validate_and_prepare_rejects_delete_cte():
    sql = "WITH d AS (DELETE FROM invoices RETURNING *) SELECT * FROM d"
    with pytest.raises(NonSelectQueryError):
        validate_and_prepare(sql, max_rows=100)
