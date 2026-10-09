"""Pruebas para bloquear funciones peligrosas de PostgreSQL."""

import pytest

from app.core.safety import DangerousFunctionError, validate_ast


# Lista fijada aquí deliberadamente: cambios en el firewall no deben cambiar estos casos.
DANGEROUS_FUNCTIONS_UNDER_TEST = (
    "pg_sleep",
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_stat_file",
    "lo_import",
    "lo_export",
    "dblink",
    "dblink_exec",
    "set_config",
    "pg_terminate_backend",
    "pg_cancel_backend",
)


@pytest.mark.parametrize("function", DANGEROUS_FUNCTIONS_UNDER_TEST)
def test_rechaza_funciones_peligrosas(function):
    with pytest.raises(DangerousFunctionError):
        validate_ast(f"SELECT {function}(1) FROM invoices")


@pytest.mark.parametrize("function", DANGEROUS_FUNCTIONS_UNDER_TEST)
def test_rechaza_funciones_peligrosas_en_mayusculas(function):
    with pytest.raises(DangerousFunctionError):
        validate_ast(f"SELECT {function.upper()}(1) FROM invoices")


@pytest.mark.parametrize("function", DANGEROUS_FUNCTIONS_UNDER_TEST)
def test_rechaza_funciones_peligrosas_con_esquema(function):
    with pytest.raises(DangerousFunctionError):
        validate_ast(f"SELECT pg_catalog.{function}(1) FROM invoices")


@pytest.mark.parametrize("function", DANGEROUS_FUNCTIONS_UNDER_TEST)
def test_rechaza_funciones_peligrosas_en_subconsulta(function):
    with pytest.raises(DangerousFunctionError):
        validate_ast(f"SELECT * FROM (SELECT {function}(1) FROM invoices) AS q")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT count(*) FROM customers",
        "SELECT now() FROM customers",
        "SELECT lower(name) FROM customers",
        "SELECT count(*), now(), lower(name) FROM customers",
    ],
)
def test_acepta_funciones_normales(sql):
    validate_ast(sql)
