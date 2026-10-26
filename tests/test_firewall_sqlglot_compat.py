"""El cortafuegos debe decidir igual con sqlglot 25.24.0 (fijada) y con sqlglot 30.x.

Escritas antes de implementar (rojas bajo sqlglot 30.18.0 por diseño); no se editan para hacerlas
pasar. Cada caso se comprobó pasando con sqlglot 25.24.0. Se corren dos veces (ver SPEC.md):
una con la versión fijada en requirements.txt y otra con `PYTHONPATH` apuntando a sqlglot 30.18.0.

Qué cambia en sqlglot 30 (medido el 2026-10-26 con 30.18.0):
- `DBMS_RANDOM.VALUE` ya no parsea como Column(table=DBMS_RANDOM): se vuelve `exp.Rand`, así que
  la regla de calificadores no declarados no lo ve.
- `FETCH FIRST n PERCENT` y `WITH TIES` ya no son los argumentos `percent`/`with_ties` de
  `exp.Fetch`: viven en `limit_options`, y `enforce_limit` no los reescribe. `10 PERCENT` de una
  tabla de un millón de filas devuelve 100.000, o sea que el tope de filas se salta.
"""

import os
import re

import pytest
import sqlglot

from app.core.safety import UnsafeQueryError, validate_and_prepare


def oracle(sql, max_rows=100, **kwargs):
    return validate_and_prepare(sql, max_rows, dialect="oracle", **kwargs)


def test_the_expected_sqlglot_is_loaded():
    # Evita correr dos veces la misma versión por un PYTHONPATH mal puesto.
    expected = os.environ.get("EXPECT_SQLGLOT")
    if expected is None:
        pytest.skip("EXPECT_SQLGLOT no está definida")
    assert sqlglot.__version__ == expected


# ------------------------------------------------- DBMS_RANDOM sin declarar como tabla
REJECT_DBMS_RANDOM = [
    "SELECT DBMS_RANDOM.VALUE FROM customers",
    "SELECT dbms_random.value FROM customers",
    "SELECT DBMS_RANDOM.VALUE AS r FROM customers",
    "SELECT * FROM customers ORDER BY DBMS_RANDOM.VALUE",
    "SELECT * FROM customers WHERE DBMS_RANDOM.VALUE > 0.5",
    "SELECT DBMS_RANDOM.RANDOM FROM customers",
    "SELECT SYS.DBMS_RANDOM.VALUE FROM customers",
    (
        "SELECT c.full_name FROM customers c WHERE c.customer_id IN "
        "(SELECT customer_id FROM invoices WHERE DBMS_RANDOM.VALUE > 0)"
    ),
    "WITH r AS (SELECT DBMS_RANDOM.VALUE AS v FROM customers) SELECT v FROM r",
]


@pytest.mark.parametrize("sql", REJECT_DBMS_RANDOM)
def test_dbms_random_is_rejected(sql):
    with pytest.raises(UnsafeQueryError):
        oracle(sql)


# ------------------------------------------------- PERCENT y WITH TIES no acotan filas
PERCENT_CASES = [
    "SELECT * FROM customers FETCH FIRST 10 PERCENT ROWS ONLY",
    "SELECT * FROM customers FETCH FIRST 50 PERCENT ROWS ONLY",
    "SELECT * FROM customers FETCH NEXT 1 PERCENT ROWS ONLY",
    "SELECT * FROM customers ORDER BY 1 OFFSET 5 ROWS FETCH FIRST 10 PERCENT ROWS ONLY",
    "SELECT * FROM customers ORDER BY 1 FETCH FIRST 10 PERCENT ROWS WITH TIES",
]

WITH_TIES_CASES = [
    "SELECT * FROM customers ORDER BY 1 FETCH FIRST 5 ROWS WITH TIES",
    "SELECT * FROM customers ORDER BY 1 FETCH NEXT 3 ROWS WITH TIES",
    "SELECT * FROM customers ORDER BY 1 FETCH FIRST 500 ROWS WITH TIES",
]


@pytest.mark.parametrize("sql", PERCENT_CASES)
def test_percent_fetch_becomes_an_absolute_cap(sql):
    out = oracle(sql)
    assert "PERCENT" not in out.upper()
    assert "TIES" not in out.upper()
    assert re.search(r"FETCH (FIRST|NEXT) 100 ROWS ONLY\s*$", out)


@pytest.mark.parametrize("sql", WITH_TIES_CASES)
def test_with_ties_becomes_rows_only_and_never_exceeds_the_cap(sql):
    out = oracle(sql)
    assert "TIES" not in out.upper()
    match = re.search(r"FETCH (?:FIRST|NEXT) (\d+) ROWS ONLY\s*$", out)
    assert match, out
    assert int(match.group(1)) <= 100


def test_a_plain_small_fetch_is_left_alone():
    out = oracle("SELECT * FROM customers ORDER BY 1 FETCH FIRST 5 ROWS ONLY")
    assert re.search(r"FETCH (FIRST|NEXT) 5 ROWS ONLY\s*$", out)
