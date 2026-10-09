import pytest

from app.core.safety import UnsafeQueryError, is_safe_select, validate_and_prepare


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * INTO newt FROM t",
        "WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d",
        "WITH d AS (INSERT INTO t VALUES (1) RETURNING *) SELECT * FROM d",
        "WITH d AS (UPDATE t SET x = 1 RETURNING *) SELECT * FROM d",
        "SELECT * FROM t FOR UPDATE",
        "SELECT * FROM t FOR SHARE",
        "SELECT * FROM (SELECT * FROM t FOR UPDATE) x",
        "WITH a AS (SELECT * FROM t FOR UPDATE) SELECT * FROM a",
        "SELECT * FROM t WHERE id IN (SELECT id FROM u FOR SHARE)",
        "WITH a AS (SELECT * INTO x FROM t) SELECT * FROM a",
    ],
)
def test_unsafe_select_shapes_are_rejected(sql):
    assert is_safe_select(sql) is False


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a FROM t",
        "WITH a AS (SELECT 1) SELECT * FROM a",
        "SELECT * FROM t WHERE x IN (SELECT y FROM u)",
    ],
)
def test_read_only_select_shapes_are_accepted(sql):
    assert is_safe_select(sql) is True


def test_validate_and_prepare_rejects_delete_cte():
    sql = "WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d"
    with pytest.raises(UnsafeQueryError):
        validate_and_prepare(sql, max_rows=100)
