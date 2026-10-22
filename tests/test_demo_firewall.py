import pytest

from app.core.safety import UnsafeQueryError, validate_and_prepare
from scripts.demo_firewall import LEGITIMATE_QUERIES, MALICIOUS_QUERIES, MAX_ROWS


@pytest.mark.parametrize("sql", LEGITIMATE_QUERIES)
def test_demo_legitimate_queries_pass(sql):
    prepared = validate_and_prepare(sql, max_rows=MAX_ROWS)
    assert prepared.startswith("SELECT ")
    assert "LIMIT " in prepared


@pytest.mark.parametrize("sql", MALICIOUS_QUERIES)
def test_demo_malicious_queries_are_blocked(sql):
    with pytest.raises(UnsafeQueryError):
        validate_and_prepare(sql, max_rows=MAX_ROWS)
