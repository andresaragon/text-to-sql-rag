"""Pruebas para bloquear funciones peligrosas de PostgreSQL."""

import pytest

from app.core.safety import DANGEROUS_FUNCTIONS, is_safe_select


@pytest.mark.parametrize("function", sorted(DANGEROUS_FUNCTIONS))
def test_rechaza_funciones_peligrosas(function):
    assert not is_safe_select(f"SELECT {function}(1)")


@pytest.mark.parametrize("function", sorted(DANGEROUS_FUNCTIONS))
def test_rechaza_funciones_peligrosas_en_mayusculas(function):
    assert not is_safe_select(f"SELECT {function.upper()}(1)")


@pytest.mark.parametrize("function", sorted(DANGEROUS_FUNCTIONS))
def test_rechaza_funciones_peligrosas_con_esquema(function):
    assert not is_safe_select(f"SELECT pg_catalog.{function}(1)")


@pytest.mark.parametrize("function", sorted(DANGEROUS_FUNCTIONS))
def test_rechaza_funciones_peligrosas_en_subconsulta(function):
    assert not is_safe_select(f"SELECT * FROM (SELECT {function}(1)) AS q")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT count(*) FROM t",
        "SELECT now()",
        "SELECT lower(name) FROM t",
        "SELECT count(*), now(), lower(name) FROM t",
    ],
)
def test_acepta_funciones_normales(sql):
    assert is_safe_select(sql)
