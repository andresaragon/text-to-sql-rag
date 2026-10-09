import pytest

from app.core.safety import enforce_limit


@pytest.mark.parametrize(
    ("sql", "max_rows", "expected"),
    [
        ("SELECT 1 LIMIT 0", 10, "SELECT 1 LIMIT 0"),
        ("select * from t limit 5;", 10, "SELECT * FROM t LIMIT 5"),
        ("SELECT * FROM t;", 10, "SELECT * FROM t LIMIT 10"),
        ("SELECT * FROM t LIMIT 10", 10, "SELECT * FROM t LIMIT 10"),
    ],
)
def test_enforce_limit_edge_cases(sql, max_rows, expected):
    assert enforce_limit(sql, max_rows) == expected
