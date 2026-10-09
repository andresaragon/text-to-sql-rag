import pytest

from app.core.safety import DangerousFunctionError, validate_ast


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT version()",
        "SELECT VERSION()",
        "SELECT pg_catalog.version()",
        "SELECT current_version()",
        "SELECT * FROM (SELECT version()) q",
    ],
)
def test_version_functions_are_blocked(sql):
    with pytest.raises(DangerousFunctionError):
        validate_ast(sql)


def test_count_is_allowed():
    validate_ast("SELECT count(*) FROM invoices")
